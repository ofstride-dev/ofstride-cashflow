"""Company-scoped bank statement parsing and AP/AR/petty-cash reconciliation."""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import azure.functions as func
from shared.admin_auth import require_cashflow_tenant
from shared.db import get_supabase_client

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None
try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None
try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
except ImportError:  # pragma: no cover
    DocumentAnalysisClient = AzureKeyCredential = None

LOGGER = logging.getLogger("ofstride.cashflow.reconcile")
MAX_UPLOAD_BYTES = int(os.getenv("CASHFLOW_RECONCILE_MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
DATE_TOLERANCE_DAYS = int(os.getenv("CASHFLOW_RECONCILE_DATE_TOLERANCE_DAYS", "3"))
AMOUNT_TOLERANCE = Decimal(os.getenv("CASHFLOW_RECONCILE_AMOUNT_TOLERANCE", "0.01"))
SUPPORTED = {".csv", ".xlsx", ".xls", ".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _response(payload: dict[str, Any], status: int = 200, mimetype: str = "application/json") -> func.HttpResponse:
    return func.HttpResponse(_json(payload), status_code=status, mimetype=mimetype)


def _error(message: str, status: int = 400) -> func.HttpResponse:
    return _response({"success": False, "error": message}, status)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", _text(value)).lower())


def _money(value: Any) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd is not None and pd.isna(value)):
        return None
    s = _text(value).upper().replace("₹", "").replace("INR", "").replace("RS.", "").replace("RS", "")
    if not s or s in {"-", "N/A", "NA", "NULL"}:
        return None
    negative = s.startswith("(") and s.endswith(")") or s.endswith("DR") or s.startswith("-")
    s = re.sub(r"[^0-9.]", "", s)
    if not s:
        return None
    try:
        result = Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return -result if negative else result
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    s = _text(value)
    if not s:
        return None
    if "T" in s:
        s = s.split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    if pd is not None:
        try:
            parsed = pd.to_datetime(s, dayfirst=True, errors="coerce")
            if not pd.isna(parsed):
                return parsed.date()
        except Exception:
            pass
    return None


def _column(columns: list[Any], *names: str) -> str | None:
    indexed = {_key(c): str(c) for c in columns}
    for name in names:
        if _key(name) in indexed:
            return indexed[_key(name)]
    for c in columns:
        k = _key(c)
        if any(_key(n) in k for n in names):
            return str(c)
    return None


def _row(raw: dict[str, Any], number: int, method: str) -> dict[str, Any] | None:
    cols = list(raw)
    date_col = _column(cols, "valueDate", "transactionDate", "date", "txnDate", "value date")
    timestamp_col = _column(cols, "transactionTimestamp", "timestamp", "datetime")
    d = _date(raw.get(date_col)) if date_col else None
    if not d and timestamp_col:
        d = _date(raw.get(timestamp_col))
    if not d:
        return None
    debit_col = _column(cols, "debit", "withdrawal", "debit amount", "withdrawal amount")
    credit_col = _column(cols, "credit", "deposit", "credit amount", "deposit amount")
    amount_col = _column(cols, "amount", "transaction amount", "txn amount")
    direction_col = _column(cols, "type", "transaction type", "dr cr", "debit credit")
    direction = _text(raw.get(direction_col)).lower() if direction_col else ""
    debit = _money(raw.get(debit_col)) if debit_col else None
    credit = _money(raw.get(credit_col)) if credit_col else None
    amount = _money(raw.get(amount_col)) if amount_col else None
    if debit is None and credit is None and amount is not None:
        if "credit" in direction or direction in {"cr", "c", "in", "deposit"}:
            credit, amount = abs(amount), abs(amount)
            direction = "credit"
        else:
            debit, amount = abs(amount), abs(amount)
            direction = "debit"
    debit = abs(debit or Decimal("0"))
    credit = abs(credit or Decimal("0"))
    if debit and credit:
        direction = "unknown"
        amount = max(debit, credit)
    elif debit:
        direction, amount = "debit", debit
    elif credit:
        direction, amount = "credit", credit
    else:
        return None
    desc_col = _column(cols, "narration", "description", "particulars", "remarks", "details")
    ref_col = _column(cols, "reference", "reference no", "utr", "txnId", "transaction id", "cheque no")
    bal_col = _column(cols, "currentBalance", "balance", "closing balance", "available balance")
    return {
        "transaction_date": d.isoformat(), "value_date": d.isoformat(),
        "description": _text(raw.get(desc_col)) if desc_col else "",
        "reference": _text(raw.get(ref_col)) if ref_col else "",
        "debit": float(debit), "credit": float(credit), "amount": float(amount),
        "direction": direction, "balance": float(_money(raw.get(bal_col))) if bal_col and _money(raw.get(bal_col)) is not None else None,
        "source_row_number": number, "extraction_method": method, "confidence": 1.0,
        "raw_data": {str(k): _text(v) for k, v in raw.items()},
    }


def _parse_csv(data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows or not rows[0]:
        raise ValueError("CSV has no header or transaction rows")
    result = [_row(r, i + 2, "csv") for i, r in enumerate(rows)]
    return [r for r in result if r], []


def _parse_excel(data: bytes, ext: str) -> tuple[list[dict[str, Any]], list[str]]:
    if pd is None:
        raise ValueError("Excel parsing dependency is unavailable")
    engine = "openpyxl" if ext == ".xlsx" else None
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, engine=engine)
    warnings: list[str] = []
    for sheet, frame in sheets.items():
        header_idx = None
        for i in range(min(len(frame), 15)):
            keys = {_key(x) for x in frame.iloc[i].tolist()}
            if keys & {"date", "valuedate", "transactiondate", "transactiontimestamp"} and keys & {"amount", "debit", "credit", "withdrawal"}:
                header_idx = i; break
        if header_idx is None:
            continue
        frame = frame.iloc[header_idx + 1:].copy()
        frame.columns = [str(x).strip() for x in sheets[sheet].iloc[header_idx].tolist()]
        parsed = [_row({str(k): v for k, v in rec.items()}, i + header_idx + 2, "xlsx") for i, rec in enumerate(frame.to_dict("records"))]
        if parsed:
            return [r for r in parsed if r], warnings
    raise ValueError("No transaction table was found in the Excel workbook")


def _parse_pdf_text(data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    if fitz is None:
        raise ValueError("PDF parsing dependency is unavailable")
    doc = fitz.open(stream=data, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    if len(re.sub(r"\s", "", text)) < 40:
        return [], ["PDF contains no usable native text; OCR fallback is required"]
    result = []
    for i, line in enumerate(text.splitlines(), 1):
        parts = re.split(r"\s{2,}|\t+|\s+", line.strip())
        if len(parts) < 3 or not _date(parts[0]):
            continue
        raw = {"date": parts[0], "description": " ".join(parts[1:-1]), "amount": parts[-1]}
        parsed = _row(raw, i, "pdf_text")
        if parsed: result.append(parsed)
    return result, []


def _parse_ocr(data: bytes, ext: str) -> tuple[list[dict[str, Any]], list[str]]:
    # Support the names already used by this repository as well as the
    # conventional Document Intelligence names used by new deployments.
    endpoint = (
        os.getenv("CASHFLOW_DOC_INTEL_ENDPOINT")
        or os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT")
        or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
        or os.getenv("AZURE_DOC_INTEL_ENDPOINT")
    )
    key = (
        os.getenv("CASHFLOW_DOC_INTEL_KEY")
        or os.getenv("AZURE_DOC_INTELLIGENCE_KEY")
        or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")
        or os.getenv("AZURE_DOC_INTEL_KEY")
    )
    if not endpoint or not key or DocumentAnalysisClient is None:
        raise ValueError("Scanned documents require configured Azure Document Intelligence endpoint and key settings")
    client = DocumentAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    poller = client.begin_analyze_document("prebuilt-layout", document=data)
    result = poller.result()
    rows = []
    for table in result.tables:
        cells = {(c.row_index, c.column_index): c.content for c in table.cells}
        headers = [cells.get((0, c), "") for c in range(table.column_count)]
        for r in range(1, table.row_count):
            raw = {headers[c] or f"column_{c}": cells.get((r, c), "") for c in range(table.column_count)}
            parsed = _row(raw, r + 1, "azure_document_intelligence")
            if parsed: rows.append(parsed)
    return rows, []


def _parse_file(name: str, data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED: raise ValueError(f"Unsupported file type: {ext or 'unknown'}")
    if ext == ".csv": return _parse_csv(data)
    if ext in {".xlsx", ".xls"}: return _parse_excel(data, ext)
    if ext == ".pdf":
        rows, warnings = _parse_pdf_text(data)
        return (rows, warnings) if rows else _parse_ocr(data, ext)
    return _parse_ocr(data, ext)


def _balance_warnings(rows: list[dict[str, Any]]) -> list[str]:
    with_balance = [r for r in rows if r.get("balance") is not None]
    if len(with_balance) < 2: return []
    warnings = []
    first = with_balance[0]
    inferred_opening = Decimal(str(first["balance"])) - Decimal(str(first["credit"])) + Decimal(str(first["debit"]))
    previous = inferred_opening
    for r in with_balance:
        expected = previous + Decimal(str(r["credit"])) - Decimal(str(r["debit"]))
        actual = Decimal(str(r["balance"]))
        if abs(expected - actual) > AMOUNT_TOLERANCE:
            warnings.append(f"Running balance mismatch near source row {r['source_row_number']}: expected {expected}, got {actual}")
        previous = actual
    return warnings[:20]


def _platform_rows(client: Any, company_id: str, start: str, end: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    queries = [
        ("cashflow_bills", "bill_date", "bill_number", "vendor_id", "amount", "ap", "debit"),
        ("cashflow_invoices", "invoice_date", "invoice_number", "customer_id", "amount", "ar", "credit"),
        ("cashflow_petty_cash", "entry_date", None, None, None, "petty_cash", None),
    ]
    for table, date_col, number_col, entity_col, amount_col, kind, expected_direction in queries:
        query = client.table(table).select("*").eq("company_id", company_id).gte(date_col, start).lte(date_col, end)
        data = query.execute().data or []
        entity_ids = {str(x.get(entity_col)): x for x in data if entity_col and x.get(entity_col)}
        entities = {}
        if entity_ids:
            response = client.table("cashflow_entities").select("id,name").eq("company_id", company_id).in_("id", list(entity_ids)).execute()
            entities = {str(x["id"]): x.get("name", "") for x in (response.data or [])}
        for item in data:
            if kind == "petty_cash":
                amount = _money(item.get("cash_out")) or _money(item.get("cash_in")) or Decimal("0")
                direction = "debit" if (_money(item.get("cash_out")) or 0) > 0 else "credit"
                number = item.get("id")
                party = item.get("description")
            else:
                amount = _money(item.get(amount_col)) or Decimal("0")
                direction = expected_direction; number = item.get(number_col); party = entities.get(str(item.get(entity_col)), "")
            rows.append({"id": item.get("id"), "kind": kind, "voucher_number": _text(number), "voucher_date": _text(item.get(date_col)), "party_name": _text(party), "amount": float(abs(amount)), "direction": direction, "raw_data": item})
    return rows


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _text(value).lower())


def _match(bank: list[dict[str, Any]], platform: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    used: set[int] = set(); counts = {"matched": 0, "amount_mismatch": 0, "missing_in_bank_statement": 0, "unexpected_in_bank_statement": 0}; details = []
    for b in bank:
        candidates = []
        for i, p in enumerate(platform):
            if i in used or b["direction"] not in {p["direction"], "unknown"}: continue
            days = abs((_date(b["transaction_date"]) - _date(p["voucher_date"])).days)
            ref = _norm(b.get("reference")); num = _norm(p.get("voucher_number"))
            score = 100 if ref and num and (ref == num or ref in num or num in ref) else 0
            if days <= DATE_TOLERANCE_DAYS: score += 20
            if abs(Decimal(str(b["amount"])) - Decimal(str(p["amount"]))) <= AMOUNT_TOLERANCE: score += 50
            if _norm(b.get("description")) and _norm(p.get("party_name")) and (_norm(p["party_name"]) in _norm(b["description"]) or _norm(b["description"]) in _norm(p["party_name"])): score += 10
            if score: candidates.append((score, i, days))
        if candidates:
            candidates.sort(reverse=True); score, idx, days = candidates[0]; p = platform[idx]
            amount_ok = abs(Decimal(str(b["amount"])) - Decimal(str(p["amount"]))) <= AMOUNT_TOLERANCE
            if amount_ok and (score >= 50): status = "matched"; used.add(idx); counts[status] += 1
            else:
                status = "amount_mismatch"; used.add(idx); counts[status] += 1
            details.append({"bank": b, "platform": p, "status": status, "notes": f"candidate score={score}; date_difference_days={days}"})
        else:
            counts["unexpected_in_bank_statement"] += 1; details.append({"bank": b, "platform": None, "status": "unexpected_in_bank_statement", "notes": "No AP, AR, or petty-cash candidate found"})
    for i, p in enumerate(platform):
        if i not in used:
            counts["missing_in_bank_statement"] += 1; details.append({"bank": None, "platform": p, "status": "missing_in_bank_statement", "notes": "No bank transaction matched"})
    return {"counts": counts, "details": details}, details


def _persist(client: Any, company_id: str, identity: dict[str, Any], start: str, end: str, name: str, ext: str, summary: dict[str, Any], details: list[dict[str, Any]]) -> str:
    run = client.table("cashflow_bank_reconcile_runs").insert({"company_id": company_id, "start_date": start, "end_date": end, "source_file_name": name, "source_file_type": ext, "summary": summary, "created_by": identity.get("user_id")}).execute()
    run_id = str((run.data or [{}])[0].get("id") or uuid.uuid4())
    inserts = []
    for d in details:
        for side, item in (("bank", d.get("bank")), ("platform", d.get("platform"))):
            if not item: continue
            inserts.append({"company_id": company_id, "run_id": run_id, "source_side": side, "voucher_type": item.get("kind", "bank"), "voucher_number": item.get("reference") or item.get("voucher_number"), "voucher_date": item.get("transaction_date") or item.get("voucher_date"), "party_name": item.get("description") or item.get("party_name"), "amount": item.get("amount", 0), "status": d["status"], "notes": d.get("notes"), "raw_data": item.get("raw_data", {})})
    for i in range(0, len(inserts), 500):
        if inserts: client.table("cashflow_bank_reconcile_rows").insert(inserts[i:i + 500]).execute()
    return run_id


def _analyze(req: func.HttpRequest, auth: dict[str, Any]) -> func.HttpResponse:
    try: body = req.get_json()
    except ValueError: return _error("Request body must be valid JSON")
    start, end = _text(body.get("start_date")), _text(body.get("end_date")); name = _text(body.get("file_name"))
    if not _date(start) or not _date(end) or _date(start) > _date(end): return _error("Valid start_date and end_date are required")
    if not name or not body.get("file_content_base64"): return _error("file_name and file_content_base64 are required")
    try: data = base64.b64decode(body["file_content_base64"], validate=True)
    except Exception: return _error("file_content_base64 is invalid")
    if len(data) > MAX_UPLOAD_BYTES: return _error("Uploaded file is too large", 413)
    try: bank, warnings = _parse_file(name, data)
    except ValueError as exc: return _error(str(exc), 422)
    warnings.extend(_balance_warnings(bank)); start_d, end_d = _date(start), _date(end)
    bank = [r for r in bank if start_d <= _date(r["transaction_date"]) <= end_d]
    uploaded = []
    for r in bank:
        issues = []
        if not r.get("transaction_date"): issues.append("Missing transaction date")
        if not r.get("description"): issues.append("Missing narration/description")
        if r.get("amount") is None or float(r.get("amount") or 0) <= 0: issues.append("Missing or invalid amount")
        uploaded.append({"row_number": r["source_row_number"], "voucher_number": r["reference"], "voucher_date": r["transaction_date"], "party_name": r["description"], "amount": r["amount"], "validation_issues": issues, "suggested_correction": "Review the source row before posting." if issues else ""})
    compare = bool(body.get("compare_with_platform")); details = []; counts = {"matched": 0, "amount_mismatch": 0, "missing_in_bank_statement": 0, "unexpected_in_bank_statement": 0}; platform = []
    if compare:
        platform = _platform_rows(get_supabase_client(), auth["company_id"], start, end); matched, details = _match(bank, platform); counts = matched["counts"]
    else:
        # Bank-only parsing is not a mismatch against an empty platform. Keep
        # rows persisted for export, but mark them internally as matched so
        # the existing database status constraint remains valid.
        details = [{"bank": item, "platform": None, "status": "matched", "notes": "Parsed bank statement; platform comparison was not requested"} for item in bank]
    summary = {"total_bank_rows": len(bank), "total_platform_rows": len(platform), **counts, "balance_warnings": warnings[:20], "comparison_mode": "platform" if compare else "bank_only"}
    client = get_supabase_client()
    run_id = _persist(client, auth["company_id"], auth.get("identity") or {}, start, end, name, Path(name).suffix.lower(), summary, details)
    persisted_rows = client.table("cashflow_bank_reconcile_rows").select("id,source_side,voucher_number,voucher_date,party_name,amount,status").eq("run_id", run_id).eq("company_id", auth["company_id"]).execute().data or []
    bank_row_by_key = {(r.get("voucher_number") or "", r.get("voucher_date") or "", round(float(r.get("amount") or 0), 2)): r for r in persisted_rows if r.get("source_side") == "bank"}
    samples = []
    for d in details:
        if d["status"] != "matched":
            item = d.get("platform") or d.get("bank") or {}; reference = item.get("voucher_number") or item.get("reference"); voucher_date = item.get("voucher_date") or item.get("transaction_date"); amount = item.get("amount", 0); persisted = bank_row_by_key.get((reference or "", voucher_date or "", round(float(amount or 0), 2)))
            samples.append({"row_id": persisted.get("id") if persisted else None, "direction": item.get("direction"), "voucher_number": reference, "voucher_date": voucher_date, "party_name": item.get("party_name") or item.get("description"), "amount": amount, "status": d["status"], "notes": d.get("notes")})
    return _response({"success": True, "data": {"run_id": run_id, "summary": summary, "sample_mismatches": samples[:50], "uploaded_rows": uploaded, "column_warnings": warnings[:20], "row_issues_count": sum(1 for row in uploaded if row["validation_issues"]), "comparison_mode": "platform" if compare else "bank_only"}})


def _add_to_books(req: func.HttpRequest, auth: dict[str, Any]) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _error("Request body must be valid JSON")
    row_id = _text(body.get("row_id"))
    category = _text(body.get("category")) or "Uncategorized"
    if not row_id:
        return _error("row_id is required")
    client = get_supabase_client()
    row_response = client.table("cashflow_bank_reconcile_rows").select("*").eq("id", row_id).eq("company_id", auth["company_id"]).limit(1).execute()
    row = (row_response.data or [None])[0]
    if not row or row.get("source_side") != "bank":
        return _error("Bank reconciliation row not found", 404)
    if row.get("status") != "unexpected_in_bank_statement":
        return _error("Only unexpected bank transactions can be added to books", 409)
    raw = row.get("raw_data") or {}
    direction = _text(raw.get("direction")).lower()
    transaction = {
        "company_id": auth["company_id"], "created_by": (auth.get("identity") or {}).get("user_id"),
        "transaction_date": row.get("voucher_date"), "amount": float(row.get("amount") or 0),
        "transaction_type": "INFLOW" if direction == "credit" else "OUTFLOW",
        "payment_mode": "bank_transfer", "reference_no": row.get("voucher_number") or "",
        "category": category,
    }
    inserted = client.table("cashflow_transactions").insert(transaction).execute()
    client.table("cashflow_bank_reconcile_rows").update({"status": "matched", "notes": f"Added to books as {category}"}).eq("id", row_id).eq("company_id", auth["company_id"]).execute()
    return _response({"success": True, "data": {"transaction": (inserted.data or [None])[0], "row_id": row_id}} , 201)


def _export(req: func.HttpRequest, auth: dict[str, Any]) -> func.HttpResponse:
    run_id, kind = _text(req.params.get("run_id")), _text(req.params.get("kind")) or "mismatch"
    if not run_id: return _error("run_id is required")
    client = get_supabase_client(); run = client.table("cashflow_bank_reconcile_runs").select("id,summary").eq("id", run_id).eq("company_id", auth["company_id"]).limit(1).execute()
    if not run.data: return _error("Reconciliation run not found", 404)
    query = client.table("cashflow_bank_reconcile_rows").select("*").eq("run_id", run_id).eq("company_id", auth["company_id"])
    if kind != "corrected": query = query.neq("status", "matched")
    rows = query.execute().data or []
    output = io.StringIO(); fields = ["source_side", "voucher_type", "voucher_number", "voucher_date", "party_name", "amount", "status", "notes"]
    bank_only = (run.data[0].get("summary") or {}).get("comparison_mode") == "bank_only"
    def export_row(row: dict[str, Any]) -> dict[str, Any]:
        result = {k: row.get(k, "") for k in fields}
        if bank_only and kind == "corrected":
            result["status"] = "parsed"
            result["notes"] = "Parsed bank statement; platform comparison was not requested"
        return result
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader(); writer.writerows(export_row(r) for r in rows)
    return func.HttpResponse(output.getvalue(), status_code=200, mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="bank_reconcile_{kind}_{run_id}.csv"'})


def _recent(req: func.HttpRequest, auth: dict[str, Any]) -> func.HttpResponse:
    try: limit = min(max(int(req.params.get("limit", "5")), 1), 50)
    except ValueError: limit = 5
    rows = get_supabase_client().table("cashflow_bank_reconcile_runs").select("*").eq("company_id", auth["company_id"]).order("created_at", desc=True).limit(limit).execute().data or []
    return _response({"success": True, "data": rows})


def main(req: func.HttpRequest) -> func.HttpResponse:
    auth = require_cashflow_tenant(req)
    if not auth.get("ok"): return _error(auth.get("error", "Authentication required"), auth.get("status_code", 401))
    action = req.route_params.get("action") or ""
    try:
        if req.method == "POST" and action == "analyze": return _analyze(req, auth)
        if req.method == "POST" and action == "add-to-books": return _add_to_books(req, auth)
        if req.method == "GET" and action == "export": return _export(req, auth)
        if req.method == "GET" and action == "recent": return _recent(req, auth)
        return _error("Unknown reconciliation route", 404)
    except Exception:
        LOGGER.exception("Bank reconciliation request failed")
        return _error("Bank reconciliation could not be completed", 500)