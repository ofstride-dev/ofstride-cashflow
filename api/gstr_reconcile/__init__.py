"""Tenant-scoped GSTR-2B versus CashPulse AP reconciliation."""
from __future__ import annotations

import base64
import io
import json
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import azure.functions as func
import pandas as pd
from openpyxl import Workbook
from openpyxl.workbook.properties import CalcProperties
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from rapidfuzz.fuzz import ratio

from shared.admin_auth import require_cashflow_tenant
from shared.db import get_supabase_client

MAX_FILES = 50
MAX_FILE_BYTES = 20 * 1024 * 1024
DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d")


def _json_response(payload: dict[str, Any], status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload, default=str), mimetype="application/json", status_code=status)


def _excel_safe(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + value
    return value


def _excel_date(value: Any) -> Any:
    parsed = _date(value)
    return parsed if parsed else _excel_safe(value)


def _build_gst_workbook(result: dict[str, Any], ar_rows: list[dict[str, Any]], ap_rows: list[dict[str, Any]]) -> bytes:
    workbook = Workbook()
    workbook.calculation = CalcProperties(calcMode="auto", fullCalcOnLoad=True, forceFullCalc=True)
    workbook.properties.creator = "CashPulse Financial Engine"
    workbook.properties.title = "GST Audit & Reconciliation Report"
    header_fill = PatternFill("solid", fgColor="1F2937")
    header_font = Font(color="FFFFFF", bold=True)
    currency_format = '₹#,##0.00;[Red](₹#,##0.00);"-"'
    status_fills = {
        "TAX_MISMATCH": PatternFill("solid", fgColor="FDE68A"),
        "MISSING_IN_2B": PatternFill("solid", fgColor="FECACA"),
        "MISSING_IN_BOOKS": PatternFill("solid", fgColor="FEF3C7"),
    }

    def add_sheet(title: str, headers: list[str], rows: list[list[Any]], monetary: set[int] = set(), dates: set[int] = set()):
        sheet = workbook.create_sheet(title)
        sheet.sheet_view.showGridLines = True
        sheet.freeze_panes = "A2"
        sheet.append(headers)
        for cell in sheet[1]:
            cell.fill = header_fill; cell.font = header_font; cell.alignment = Alignment(horizontal="center", vertical="center")
        for row in rows:
            sheet.append([_excel_safe(value) for value in row])
        for column_index in monetary:
            for cell in list(sheet.columns)[column_index - 1][1:]:
                cell.number_format = currency_format
        for column_index in dates:
            for cell in list(sheet.columns)[column_index - 1][1:]:
                cell.number_format = "yyyy-mm-dd"
        for column in sheet.columns:
            width = min(max(max(len(str(cell.value or "")) for cell in column) + 5, 12), 42)
            sheet.column_dimensions[get_column_letter(column[0].column)].width = width
        return sheet

    audit_rows = []
    for bucket, label in (("matched", "MATCHED"), ("tax_mismatches", "TAX_MISMATCH"), ("missing_in_2b", "MISSING_IN_2B"), ("missing_in_books", "MISSING_IN_BOOKS")):
        for item in result.get(bucket) or []:
            portal = item.get("gstr2b") or item
            books = item.get("books") or item
            audit_rows.append([
                portal.get("invoice_number") or books.get("invoice_number"),
                portal.get("supplier_gstin") or books.get("supplier_gstin"),
                _excel_date(portal.get("invoice_date") or books.get("invoice_date")),
                portal.get("taxable_value", 0), total_tax(portal),
                books.get("taxable_value", 0), total_tax(books), item.get("tax_variance", 0),
                label, "Review tax variance" if label == "TAX_MISMATCH" else "Safe ITC" if label == "MATCHED" else "Follow up",
            ])
    audit_sheet = add_sheet("GSTR-2B Recon Audit", ["Invoice Number", "Supplier GSTIN", "Invoice Date", "Portal Taxable Value", "Portal Tax", "Book Taxable Value", "Book Tax", "Tax Variance", "Status", "Recommended Action"], audit_rows, {4, 5, 6, 7, 8}, {3})
    for row in audit_sheet.iter_rows(min_row=2):
        fill = status_fills.get(str(row[8].value))
        if fill:
            for cell in row: cell.fill = fill

    gstr1_rows = []
    for row in ar_rows:
        customer = row.get("cashflow_entities") or {}
        gst = _money(row.get("gst_amount")); amount = _money(row.get("amount")); split = _tax_split(row)
        gstr1_rows.append([customer.get("gstin", ""), customer.get("name", ""), row.get("invoice_number", ""), _excel_date(row.get("invoice_date")), amount + gst, "", "N", "Regular B2B", max(amount - gst, 0), split["igst"], split["cgst"], split["sgst"]])
    add_sheet("GSTR-1 B2B", ["GSTIN/UIN of Recipient", "Receiver Name", "Invoice Number", "Invoice Date", "Invoice Value", "Place Of Supply", "Reverse Charge", "Invoice Type", "Taxable Value", "Integrated Tax", "Central Tax", "State/UT Tax"], gstr1_rows, {5, 9, 10, 11, 12}, {4})

    matched_books = [item.get("books") or {} for item in result.get("matched") or []]
    outward = [sum(_money(row.get("amount")) for row in ar_rows), 0, 0, 0]
    for row in ar_rows:
        split = _tax_split(row); outward[1] += split["igst"]; outward[2] += split["cgst"]; outward[3] += split["sgst"]
    itc = [sum(_money(row.get("taxable_value")) for row in matched_books), sum(_money(row.get("igst")) for row in matched_books), sum(_money(row.get("cgst")) for row in matched_books), sum(_money(row.get("sgst")) for row in matched_books)]
    summary = add_sheet("GSTR-3B Summary", ["Section", "Taxable Value", "IGST", "CGST", "SGST", "Total"], [["3.1 Outward Taxable Supplies", outward[0], outward[1], outward[2], outward[3], "=C2+D2+E2"], ["4 Eligible ITC", itc[0], itc[1], itc[2], itc[3], "=C3+D3+E3"], ["Net Payable", "=B2-B3", "=C2-C3", "=D2-D3", "=E2-E3", "=F2-F3"]], {2, 3, 4, 5, 6})
    summary.protection.sheet = True

    add_sheet("AP ITC Source Details", ["Supplier GSTIN", "Bill Number", "Issue Date", "Taxable Value", "IGST", "CGST", "SGST", "Status"], [[row.get("supplier_gstin") or (row.get("cashflow_entities") or {}).get("gstin", ""), row.get("bill_number"), _excel_date(row.get("bill_date")), row.get("taxable_value") or max(_money(row.get("amount")) - _money(row.get("gst_amount")), 0), row.get("igst_amount", 0), row.get("cgst_amount", 0), row.get("sgst_amount", 0), row.get("status", "")] for row in ap_rows], {4, 5, 6, 7}, {3})
    add_sheet("AR Source Details", ["Customer GSTIN", "Invoice Number", "Invoice Date", "Taxable Value", "IGST", "CGST", "SGST", "Status"], [[(row.get("cashflow_entities") or {}).get("gstin", ""), row.get("invoice_number"), _excel_date(row.get("invoice_date")), max(_money(row.get("amount")) - _money(row.get("gst_amount")), 0), _tax_split(row)["igst"], _tax_split(row)["cgst"], _tax_split(row)["sgst"], row.get("status", "")] for row in ar_rows], {4, 5, 6, 7}, {3})
    workbook.remove(workbook["Sheet"])
    output = io.BytesIO(); workbook.save(output); return output.getvalue()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _money(value: Any) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", _text(value).replace(",", ""))
    try:
        return round(float(cleaned or 0), 2)
    except ValueError:
        return 0.0


def _date(value: Any) -> date | None:
    raw = _text(value)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def clean_invoice_number(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _text(value).upper())


def clean_gstin(value: Any) -> str:
    return re.sub(r"\s+", "", _text(value).upper())


def total_tax(row: dict[str, Any]) -> float:
    return round(sum(_money(row.get(key)) for key in ("cgst", "sgst", "igst", "cgst_amount", "sgst_amount", "igst_amount")), 2)


def _normalize_2b_row(raw: dict[str, Any], filename: str) -> dict[str, Any]:
    return {
        "source": "gstr2b",
        "source_file": filename,
        "supplier_gstin": clean_gstin(raw.get("supplier_gstin") or raw.get("GSTIN") or raw.get("gstin")),
        "invoice_number": _text(raw.get("invoice_number") or raw.get("invoice_num") or raw.get("Invoice Number") or raw.get("invoice_no")),
        "invoice_date": _date(raw.get("invoice_date") or raw.get("Invoice Date") or raw.get("date")),
        "taxable_value": _money(raw.get("taxable_value") or raw.get("Taxable Value")),
        "cgst": _money(raw.get("cgst") or raw.get("CGST")),
        "sgst": _money(raw.get("sgst") or raw.get("SGST")),
        "igst": _money(raw.get("igst") or raw.get("IGST")),
    }


def _nested_2b_rows(parsed: Any) -> list[dict[str, Any]]:
    """Flatten standard GSTR-2B data.b2b[].inv[] records."""
    if isinstance(parsed, list):
        return [row for row in parsed if isinstance(row, dict)]
    if not isinstance(parsed, dict):
        return []
    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
    b2b = data.get("b2b") or []
    flattened = []
    for vendor in b2b:
        if not isinstance(vendor, dict):
            continue
        ctin = vendor.get("ctin") or vendor.get("supplier_gstin") or vendor.get("gstin")
        for invoice in vendor.get("inv") or vendor.get("invoices") or []:
            if not isinstance(invoice, dict):
                continue
            tax = {"cgst": 0, "sgst": 0, "igst": 0}
            items = invoice.get("itms") or invoice.get("items") or []
            for item in items:
                detail = item.get("itm_det") if isinstance(item, dict) and isinstance(item.get("itm_det"), dict) else item
                if isinstance(detail, dict):
                    for key in tax:
                        tax[key] += _money(detail.get(key))
            flattened.append({
                "supplier_gstin": ctin,
                "invoice_number": invoice.get("inum") or invoice.get("invoice_number") or invoice.get("invoice_num"),
                "invoice_date": invoice.get("idt") or invoice.get("dt") or invoice.get("invoice_date") or invoice.get("date"),
                "taxable_value": invoice.get("txval") or invoice.get("taxable_value") or invoice.get("val"),
                "cgst": invoice.get("cgst", tax["cgst"]),
                "sgst": invoice.get("sgst", tax["sgst"]),
                "igst": invoice.get("igst", tax["igst"]),
            })
    if flattened:
        return flattened
    return data.get("invoices") or data.get("rows") or data.get("b2b") or []


def _read_2b_file(filename: str, content: bytes) -> list[dict[str, Any]]:
    extension = os.path.splitext(filename.lower())[1]
    if extension == ".json":
        parsed = json.loads(content.decode("utf-8-sig"))
        rows = _nested_2b_rows(parsed)
    elif extension == ".xlsx":
        rows = pd.read_excel(io.BytesIO(content), dtype=object).fillna("").to_dict("records")
    else:
        raise ValueError(f"Unsupported GSTR-2B file type: {extension or 'unknown'}")
    return [_normalize_2b_row(row, filename) for row in rows if isinstance(row, dict)]


def deduplicate_2b(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["supplier_gstin"], clean_invoice_number(row["invoice_number"]), str(row["invoice_date"] or ""))
        unique.setdefault(key, row)
    return list(unique.values())


def _tax_split(raw: dict[str, Any]) -> dict[str, float]:
    raw_data = raw.get("ocr_raw_data") or {}
    return {
        "cgst": _money(raw.get("cgst_amount") or raw_data.get("cgst") or raw_data.get("cgst_amount")),
        "sgst": _money(raw.get("sgst_amount") or raw_data.get("sgst") or raw_data.get("sgst_amount")),
        "igst": _money(raw.get("igst_amount") or raw_data.get("igst") or raw_data.get("igst_amount")),
    }


def _normalize_book_row(raw: dict[str, Any]) -> dict[str, Any]:
    gross = _money(raw.get("amount"))
    gst = _money(raw.get("gst_amount"))
    split = _tax_split(raw)
    if total_tax(split) == 0 and gst:
        split["igst"] = gst
    return {
        "source": "books",
        "id": raw.get("id"),
        "supplier_gstin": clean_gstin(raw.get("supplier_gstin") or (raw.get("cashflow_entities") or {}).get("gstin")),
        "invoice_number": _text(raw.get("bill_number")),
        "invoice_date": _date(raw.get("bill_date")),
        "taxable_value": _money(raw.get("taxable_value")) or round(max(gross - gst, 0), 2),
        **split,
        "vendor_name": (raw.get("cashflow_entities") or {}).get("name") or "",
        "gross_amount": gross,
    }


def _match_key(row: dict[str, Any]) -> tuple[str, str]:
    return row["supplier_gstin"], clean_invoice_number(row["invoice_number"])

def _identity_compatible(book: dict[str, Any], portal: dict[str, Any]) -> bool:
    return not book["supplier_gstin"] or not portal["supplier_gstin"] or book["supplier_gstin"] == portal["supplier_gstin"]


def _match_record(book: dict[str, Any], portal: dict[str, Any], tier: str, similarity: float | None = None) -> dict[str, Any]:
    return {"tier": tier, "similarity": similarity, "books": book, "gstr2b": portal, "tax_variance": round(abs(total_tax(book) - total_tax(portal)), 2)}


def match_exact(books: list[dict[str, Any]], portal: list[dict[str, Any]], used_books: set[int], used_portal: set[int], tax_tolerance: float = 1.0) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], list[int]] = {}
    for index, row in enumerate(portal):
        by_key.setdefault(_match_key(row), []).append(index)
    matches = []
    for book_index, book in enumerate(books):
        if book_index in used_books:
            continue
        candidates = by_key.get(_match_key(book), [])
        if not candidates and not book["supplier_gstin"]:
            candidates = [index for index, row in enumerate(portal) if clean_invoice_number(row["invoice_number"]) == clean_invoice_number(book["invoice_number"]) and _identity_compatible(book, row)]
        selected = next((item for item in candidates if item not in used_portal and abs(total_tax(book) - total_tax(portal[item])) <= tax_tolerance), None)
        if selected is not None:
            used_books.add(book_index); used_portal.add(selected)
            matches.append(_match_record(book, portal[selected], "MATCHED_EXACT", 100.0))
    return matches


def match_fuzzy(books: list[dict[str, Any]], portal: list[dict[str, Any]], used_books: set[int], used_portal: set[int], similarity_threshold: float = 85.0, tax_tolerance: float = 10.0, date_window: int = 3) -> list[dict[str, Any]]:
    matches = []
    for book_index, book in enumerate(books):
        if book_index in used_books or not book["supplier_gstin"]:
            continue
        candidates = []
        for portal_index, candidate in enumerate(portal):
            if portal_index in used_portal or not _identity_compatible(book, candidate):
                continue
            if book["invoice_date"] and candidate["invoice_date"] and abs((book["invoice_date"] - candidate["invoice_date"]).days) > date_window:
                continue
            variance = abs(total_tax(book) - total_tax(candidate))
            score = float(ratio(book["invoice_number"], candidate["invoice_number"]))
            if score > similarity_threshold and variance <= tax_tolerance:
                candidates.append((score, -variance, portal_index))
        if candidates:
            score, _, portal_index = max(candidates)
            used_books.add(book_index); used_portal.add(portal_index)
            matches.append(_match_record(book, portal[portal_index], "MATCHED_FUZZY", round(score, 2)))
    return matches


def classify_exact_identity_tax_mismatches(books: list[dict[str, Any]], portal: list[dict[str, Any]], used_books: set[int], used_portal: set[int], tax_tolerance: float = 1.0) -> list[dict[str, Any]]:
    """Remove same-identity records with material tax variance before fuzzy matching."""
    portal_by_key: dict[tuple[str, str], list[int]] = {}
    for portal_index, row in enumerate(portal):
        portal_by_key.setdefault(_match_key(row), []).append(portal_index)
    mismatches = []
    for book_index, book in enumerate(books):
        if book_index in used_books:
            continue
        candidate = next((index for index in portal_by_key.get(_match_key(book), []) if index not in used_portal), None)
        if candidate is not None and abs(total_tax(book) - total_tax(portal[candidate])) > tax_tolerance:
            used_books.add(book_index); used_portal.add(candidate)
            mismatches.append(_match_record(book, portal[candidate], "TAX_MISMATCH"))
    return mismatches


def _azure_semantic_matches(book_rows: list[dict[str, Any]], portal_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    endpoint = _text(os.getenv("AZURE_OPENAI_ENDPOINT"))
    api_key = _text(os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY"))
    deployment = _text(os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"))
    if not endpoint or not api_key or not deployment or not book_rows or not portal_rows:
        return []
    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"))
        prompt = {"books": [_compact(row) for row in book_rows], "gstr2b": [_compact(row) for row in portal_rows]}
        response = client.chat.completions.create(
            model=deployment,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You reconcile GST invoices. Return only JSON: {\"matches\":[{\"book_index\":number,\"portal_index\":number,\"matched\":boolean,\"reason\":string}]}. Match only when the records clearly represent the same transaction. Never invent indexes."},
                {"role": "user", "content": json.dumps(prompt, default=str)},
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        return parsed.get("matches") if isinstance(parsed.get("matches"), list) else []
    except Exception:
        return []


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    return {key: (value.isoformat() if isinstance(value, date) else value) for key, value in row.items() if key not in {"raw_data", "ocr_raw_data"}}


def reconcile(books: list[dict[str, Any]], portal: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    used_books: set[int] = set(); used_portal: set[int] = set(); matched: list[dict[str, Any]] = []
    tax_mismatches = classify_exact_identity_tax_mismatches(books, portal, used_books, used_portal)
    matched.extend(match_exact(books, portal, used_books, used_portal))
    matched.extend(match_fuzzy(books, portal, used_books, used_portal))
    remaining_books = [row for index, row in enumerate(books) if index not in used_books]
    remaining_portal = [row for index, row in enumerate(portal) if index not in used_portal]
    llm_rows = _azure_semantic_matches(remaining_books, remaining_portal)
    for item in llm_rows:
        if not item.get("matched"): continue
        book_index, portal_index = item.get("book_index"), item.get("portal_index")
        if not isinstance(book_index, int) or not isinstance(portal_index, int) or book_index >= len(remaining_books) or portal_index >= len(remaining_portal): continue
        matched.append({"tier": "MATCHED_LLM", "similarity": None, "reason": _text(item.get("reason")), "requires_review": True, "books": remaining_books[book_index], "gstr2b": remaining_portal[portal_index]})
        used_books.add(books.index(remaining_books[book_index])); used_portal.add(portal.index(remaining_portal[portal_index]))
    for book_index, book in enumerate(books):
        if book_index in used_books: continue
        for portal_index, candidate in enumerate(portal):
            if portal_index in used_portal or _match_key(book) != _match_key(candidate): continue
            if abs(total_tax(book) - total_tax(candidate)) > 1:
                tax_mismatches.append(_match_record(book, candidate, "TAX_MISMATCH")); used_books.add(book_index); used_portal.add(portal_index); break
    return {"matched": matched, "missing_in_2b": [row for index, row in enumerate(books) if index not in used_books], "missing_in_books": [row for index, row in enumerate(portal) if index not in used_portal], "tax_mismatches": tax_mismatches}


def _books(client: Any, company_id: str) -> list[dict[str, Any]]:
    response = client.table("cashflow_bills").select("*,cashflow_entities!cashflow_bills_vendor_id_fkey(name,gstin)").eq("company_id", company_id).execute()
    return [_normalize_book_row(row) for row in (response.data or [])]


def _export(req: func.HttpRequest, auth: dict[str, Any]) -> func.HttpResponse:
    body = req.get_json()
    result = body.get("result") if isinstance(body, dict) else None
    period = _text(body.get("period")) if isinstance(body, dict) else "report"
    if not isinstance(result, dict):
        return _json_response({"ok": False, "error": "A reconciliation result is required."}, 400)
    client = get_supabase_client(); company_id = auth["company_id"]
    try:
        start = datetime.strptime(period, "%m%Y").date().replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        ar_rows = client.table("cashflow_invoices").select("*,cashflow_entities!cashflow_invoices_customer_id_fkey(name,gstin)").eq("company_id", company_id).gte("invoice_date", start.isoformat()).lte("invoice_date", end.isoformat()).execute().data or []
        ap_rows = client.table("cashflow_bills").select("*,cashflow_entities!cashflow_bills_vendor_id_fkey(name,gstin)").eq("company_id", company_id).gte("bill_date", start.isoformat()).lte("bill_date", end.isoformat()).execute().data or []
        workbook_bytes = _build_gst_workbook(result, ar_rows, ap_rows)
        return func.HttpResponse(workbook_bytes, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="gstr_report_{period}.xlsx"'})
    except Exception as error:
        return _json_response({"ok": False, "error": "GST report could not be generated", "detail": str(error)}, 500)


def main(req: func.HttpRequest) -> func.HttpResponse:
    auth = require_cashflow_tenant(req)
    if not auth.get("ok"):
        return _json_response({"ok": False, "error": auth.get("error", "Authentication required")}, auth.get("status_code", 401))
    try:
        if req.method == "POST" and req.route_params.get("action") == "export":
            return _export(req, auth)
        body = req.get_json()
        if not isinstance(body, dict) or not re.fullmatch(r"\d{6}", _text(body.get("period"))):
            return _json_response({"ok": False, "error": "period is required in MMYYYY format"}, 400)
        files = body.get("files")
        if not isinstance(files, list) or not files or len(files) > MAX_FILES:
            return _json_response({"ok": False, "error": f"files must contain 1-{MAX_FILES} JSON/XLSX files"}, 400)
        company_id = auth["company_id"]
        if _text(body.get("client_id")) and _text(body.get("client_id")) != company_id:
            return _json_response({"ok": False, "error": "client_id does not match the authenticated workspace"}, 403)
        portal_rows = []
        for item in files:
            filename = _text(item.get("filename")); file_type = _text(item.get("file_type")).lower(); encoded = _text(item.get("content"))
            if file_type not in {"json", "xlsx"} or not filename or not encoded: return _json_response({"ok": False, "error": "Each file requires filename, file_type json/xlsx, and content"}, 400)
            decoded = base64.b64decode(encoded, validate=True)
            if len(decoded) > MAX_FILE_BYTES: return _json_response({"ok": False, "error": f"File {filename} exceeds the size limit"}, 413)
            portal_rows.extend(_read_2b_file(filename, decoded))
        result = reconcile(_books(get_supabase_client(), company_id), deduplicate_2b(portal_rows))
        return _json_response({"ok": True, "data": {"period": body["period"], "files_processed": len(files), "portal_records": len(portal_rows), **result}})
    except (ValueError, InvalidOperation) as error:
        return _json_response({"ok": False, "error": str(error)}, 422)
    except Exception:
        return _json_response({"ok": False, "error": "GSTR-2B reconciliation could not be completed"}, 500)
