"""Tenant-scoped Tally Prime import and export endpoint."""
from __future__ import annotations

import base64
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import azure.functions as func
import pandas as pd

from shared.admin_auth import require_cashflow_tenant
from shared.db import get_supabase_client
from shared.tenant import audit, TenantContext

GSTIN_RE = re.compile(r"^[0-9A-Z]{15}$", re.I)
SUPPORTED = {".xml", ".json", ".xlsx"}

def _text(value):
    return str(value or "").strip()

def _tag(element):
    return element.tag.rsplit("}", 1)[-1].upper()

def _date(value):
    raw = _text(value)
    if not re.fullmatch(r"\d{8}", raw):
        raise ValueError(f"Invalid Tally date: {raw or 'empty'}")
    return datetime.strptime(raw, "%Y%m%d").date().isoformat()

def _amount(value):
    try:
        return abs(float(_text(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0.0

def _debit_credit(amount, deemed_positive):
    return "debit" if _text(deemed_positive).lower() == "yes" else "credit"

def _record_ledger(node):
    values = {_tag(child): _text(child.text) for child in node}
    parent = values.get("PARENT", "")
    entity_type = "vendor" if "sundry creditor" in parent.lower() else "customer" if "sundry debtor" in parent.lower() else None
    if not entity_type:
        return None
    gstin = values.get("PARTYGSTIN", "").upper()
    return {"name": values.get("LEDGERNAME", "") or "Unnamed Ledger", "entity_type": entity_type, "gstin": gstin or None, "gstin_status": "registered" if GSTIN_RE.fullmatch(gstin) else "unregistered"}

def _record_voucher(node):
    values = {_tag(child): _text(child.text) for child in node if _tag(child) not in {"BILLALLOCATIONS.LIST", "ALLLEDGERENTRIES.LIST"}}
    voucher_type = values.get("VOUCHERTYPENAME", "").lower()
    if not voucher_type or not values.get("VOUCHERNUMBER") or voucher_type not in {"sales", "purchase", "receipt", "payment"}:
        return None
    allocation_amount = sum(_amount(child.text) for child in node.iter() if _tag(child) == "AMOUNT" and any(_tag(parent) == "BILLALLOCATIONS.LIST" for parent in []))
    # ElementTree does not expose parents; bill rows are found by walking each voucher child.
    allocation_amount = 0.0
    for allocation in [child for child in node.iter() if _tag(child) == "BILLALLOCATIONS.LIST"]:
        for amount in allocation.iter():
            if _tag(amount) == "AMOUNT": allocation_amount += _amount(amount.text)
    amount = allocation_amount or sum(_amount(child.text) for child in node.iter() if _tag(child) == "AMOUNT")
    deemed_positive = values.get("ISDEEMEDPOSITIVE", "")
    return {"invoice_id": values["VOUCHERNUMBER"], "remote_id": values.get("REMOTEID") or None, "invoice_date": _date(values.get("DATE")), "total_amount": amount, "direction": _debit_credit(amount, deemed_positive), "voucher_type": voucher_type, "party_name": values.get("PARTYLEDGERNAME") or values.get("LEDGERNAME") or "Tally Voucher"}

def _parse_xml(raw):
    root = ET.fromstring(raw)
    ledgers = [_record_ledger(node) for node in root.iter() if _tag(node) == "LEDGER"]
    vouchers = [_record_voucher(node) for node in root.iter() if _tag(node) == "VOUCHER"]
    return {"ledgers": [item for item in ledgers if item], "vouchers": [item for item in vouchers if item]}

def _parse_json(raw):
    source = json.loads(raw.decode("utf-8"))
    return {"ledgers": source.get("ledgers", source.get("LEDGERS", [])), "vouchers": source.get("vouchers", source.get("VOUCHERS", []))}

def _parse_file(name, raw):
    extension = Path(name).suffix.lower()
    if extension not in SUPPORTED: raise ValueError("Only .xml, .json, and .xlsx Tally files are supported")
    if extension == ".xml": return _parse_xml(raw)
    if extension == ".json": return _parse_json(raw)
    rows = pd.read_excel(io.BytesIO(raw)).fillna("").to_dict("records")
    return {"ledgers": [], "vouchers": rows}

def _json_response(data, status=200):
    return func.HttpResponse(json.dumps(data, default=str), mimetype="application/json", status_code=status)

def _entity(client, company_id, record):
    found = client.table("cashflow_entities").select("id").eq("company_id", company_id).eq("name", record["name"]).eq("entity_type", record["entity_type"]).limit(1).execute().data or []
    payload = {"company_id": company_id, "name": record["name"], "entity_type": record["entity_type"], "gstin": record.get("gstin"), "bank_details": {"tally_gstin_status": record.get("gstin_status")}}
    if found: return found[0]["id"]
    return (client.table("cashflow_entities").insert(payload).execute().data or [{}])[0].get("id")

def _dashboard(client, company_id):
    invoices = client.table("cashflow_invoices").select("amount,gst_amount").eq("company_id", company_id).in_("status", ["pending", "approved", "overdue"]).execute().data or []
    bills = client.table("cashflow_bills").select("amount,gst_amount").eq("company_id", company_id).in_("status", ["pending", "approved", "overdue"]).execute().data or []
    transactions = client.table("cashflow_transactions").select("amount,transaction_type").eq("company_id", company_id).execute().data or []
    inflow = sum(float(row.get("amount") or 0) for row in transactions if row.get("transaction_type") == "INFLOW")
    outflow = sum(float(row.get("amount") or 0) for row in transactions if row.get("transaction_type") == "OUTFLOW")
    return {"total_accounts_receivable": round(sum(float(row.get("amount") or 0) + float(row.get("gst_amount") or 0) for row in invoices), 2), "total_accounts_payable": round(sum(float(row.get("amount") or 0) + float(row.get("gst_amount") or 0) for row in bills), 2), "net_cash_flow": round(inflow - outflow, 2), "inflow": round(inflow, 2), "outflow": round(outflow, 2)}

def _import(req, auth):
    body = req.get_json()
    raw = base64.b64decode(body.get("file_content_base64", ""), validate=True)
    parsed = _parse_file(body.get("file_name", ""), raw)
    client = get_supabase_client(); company_id = auth["company_id"]; identity = auth.get("identity") or {}
    tenant_context = TenantContext(user_id=str(identity.get("user_id") or ""), company_id=company_id, role=str(identity.get("role") or ""), email=identity.get("email"), full_name=identity.get("full_name"))
    counts = {"imported": 0, "updated": 0, "skipped": 0, "errors": 0}
    duplicates = []
    entity_ids = {}
    for ledger in parsed["ledgers"]:
        entity_ids[(ledger["name"], ledger["entity_type"])] = _entity(client, company_id, ledger)
    for voucher in parsed["vouchers"]:
        try:
            voucher_type = _text(voucher.get("voucher_type")).lower()
            number = _text(voucher.get("invoice_id") or voucher.get("VOUCHERNUMBER"))
            date_value = voucher.get("invoice_date") or _date(voucher.get("DATE"))
            amount = _amount(voucher.get("total_amount") or voucher.get("AMOUNT"))
            party = _text(voucher.get("party_name") or voucher.get("PARTYLEDGERNAME"))
            if not number: counts["skipped"] += 1; continue
            source = {"company_id": company_id, "invoice_id": number, "remote_id": voucher.get("remote_id") or voucher.get("REMOTEID"), "voucher_type": voucher_type, "voucher_date": date_value, "total_amount": amount, "direction": _debit_credit(amount, voucher.get("ISDEEMEDPOSITIVE")), "raw_data": voucher, "created_by": identity.get("user_id")}
            existing = []
            if source["remote_id"]:
                existing = client.table("cashflow_tally_records").select("id,invoice_id").eq("company_id", company_id).eq("remote_id", source["remote_id"]).limit(1).execute().data or []
            if not existing:
                existing = client.table("cashflow_tally_records").select("id,invoice_id").eq("company_id", company_id).eq("invoice_id", number).limit(1).execute().data or []
            if existing:
                client.table("cashflow_tally_records").update(source).eq("id", existing[0]["id"]).eq("company_id", company_id).execute()
                counts["updated"] += 1
                duplicates.append({"invoice_id": number, "remote_id": source["remote_id"], "reason": "REMOTEID" if source["remote_id"] else "invoice_id"})
                continue
            client.table("cashflow_tally_records").insert(source).execute(); counts["imported"] += 1
            if voucher_type in {"sales", "purchase"}:
                entity_type = "customer" if voucher_type == "sales" else "vendor"
                entity_id = entity_ids.get((party, entity_type)) or _entity(client, company_id, {"name": party or "Tally Party", "entity_type": entity_type, "gstin": None, "gstin_status": "unregistered"})
                table = "cashflow_invoices" if voucher_type == "sales" else "cashflow_bills"; number_column = "invoice_number" if voucher_type == "sales" else "bill_number"; date_column = "invoice_date" if voucher_type == "sales" else "bill_date"; entity_column = "customer_id" if voucher_type == "sales" else "vendor_id"
                payload = {"company_id": company_id, entity_column: entity_id, number_column: number, date_column: date_value, "due_date": date_value, "payment_terms_days": 0, "amount": amount, "gst_amount": 0, "status": "pending", "created_by": identity.get("user_id")} if voucher_type == "purchase" else {"company_id": company_id, entity_column: entity_id, number_column: number, date_column: date_value, "due_date": date_value, "amount": amount, "gst_amount": 0, "status": "pending", "is_proforma": False, "created_by": identity.get("user_id")}
                client.table(table).upsert(payload, on_conflict=f"company_id,{number_column}").execute()
            elif voucher_type in {"receipt", "payment"}:
                client.table("cashflow_transactions").insert({"company_id": company_id, "transaction_date": date_value, "amount": amount, "transaction_type": "INFLOW" if voucher_type == "receipt" else "OUTFLOW", "payment_mode": "tally", "reference_no": number, "category": "Cash Collected" if voucher_type == "receipt" else "Cash Disbursed", "created_by": identity.get("user_id")}).execute()
        except Exception:
            counts["errors"] += 1
    audit.record(client, tenant_context, "upload", "tally_import", None, "success", {"counts": counts, "duplicates": duplicates})
    return _json_response({"ok": True, "data": {**counts, "duplicates": duplicates, "dashboard": _dashboard(client, company_id)}})

def _export(req, auth):
    client = get_supabase_client(); company_id = auth["company_id"]; kind = _text(req.params.get("kind"))
    if kind == "gst_summary":
        rows = client.table("cashflow_invoices").select("invoice_number,invoice_date,amount,gst_amount").eq("company_id", company_id).execute().data or []
        output = io.BytesIO(); pd.DataFrame(rows).to_excel(output, index=False, sheet_name="GST Summary"); return func.HttpResponse(output.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="GST_Summary.xlsx"'})
    if kind == "sales":
        rows = client.table("cashflow_invoices").select("invoice_number,invoice_date,amount").eq("company_id", company_id).execute().data or []; root = ET.Element("ENVELOPE"); body = ET.SubElement(root, "BODY"); data = ET.SubElement(body, "IMPORTDATA"); request = ET.SubElement(data, "REQUESTDATA")
        for row in rows:
            voucher = ET.SubElement(request, "VOUCHER", VCHTYPE="Sales"); ET.SubElement(voucher, "VOUCHERNUMBER").text = _text(row.get("invoice_number")); ET.SubElement(voucher, "DATE").text = _text(row.get("invoice_date", "")).replace("-", ""); ET.SubElement(voucher, "AMOUNT").text = str(row.get("amount") or 0)
        return func.HttpResponse(ET.tostring(root, encoding="unicode"), mimetype="application/xml", headers={"Content-Disposition": 'attachment; filename="Sales_Vouchers.xml"'})
    rows = client.table("cashflow_transactions").select("transaction_date,amount,transaction_type,reference_no").eq("company_id", company_id).execute().data or []; root = ET.Element("ENVELOPE"); body = ET.SubElement(root, "BODY"); data = ET.SubElement(body, "IMPORTDATA"); request = ET.SubElement(data, "REQUESTDATA")
    for row in rows:
        voucher = ET.SubElement(request, "VOUCHER", VCHTYPE="Receipt" if row.get("transaction_type") == "INFLOW" else "Payment"); ET.SubElement(voucher, "VOUCHERNUMBER").text = _text(row.get("reference_no")); ET.SubElement(voucher, "DATE").text = _text(row.get("transaction_date", "")).replace("-", ""); ET.SubElement(voucher, "AMOUNT").text = str(row.get("amount") or 0)
    return func.HttpResponse(ET.tostring(root, encoding="unicode"), mimetype="application/xml", headers={"Content-Disposition": 'attachment; filename="Bank_Receipts.xml"'})

def main(req: func.HttpRequest) -> func.HttpResponse:
    auth = require_cashflow_tenant(req)
    if not auth.get("ok"): return _json_response({"ok": False, "error": auth.get("error", "Authentication required")}, auth.get("status_code", 401))
    try:
        if req.method == "POST" and req.route_params.get("action") == "import": return _import(req, auth)
        if req.method == "GET" and req.route_params.get("action") == "export": return _export(req, auth)
        return _json_response({"ok": False, "error": "Unknown Tally Sync route"}, 404)
    except Exception as error:
        return _json_response({"ok": False, "error": str(error)}, 422)
