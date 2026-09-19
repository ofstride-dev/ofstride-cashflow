"""Tenant-scoped Tally Prime import and export endpoint."""
from __future__ import annotations

import base64
import io
import json
import logging
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
LOGGER = logging.getLogger("ofstride.cashflow.tally_sync")

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

def _bill_allocations(node):
    allocations = []
    for allocation in [child for child in node.iter() if _tag(child) == "BILLALLOCATIONS.LIST"]:
        values = {_tag(child): _text(child.text) for child in allocation.iter() if child is not allocation}
        reference = values.get("NAME") or values.get("BILLNAME") or values.get("REFERENCE")
        if reference:
            allocations.append({"reference": reference, "amount": _amount(values.get("AMOUNT")), "bill_type": values.get("BILLTYPE", "Agst Ref")})
    return allocations

def _first_value(node, *names):
    wanted = {name.upper() for name in names}
    for child in node.iter():
        if _tag(child) in wanted and _text(child.text):
            return _text(child.text)
    return ""

def _purchase_or_sales_party(node):
    """Read the party ledger from nested Tally ledger-entry nodes."""
    entries = [child for child in node.iter() if _tag(child) == "ALLLEDGERENTRIES.LIST"]
    for entry in entries:
        deemed_positive = _first_value(entry, "ISDEEMEDPOSITIVE").lower()
        party = _first_value(entry, "PARTYLEDGERNAME", "LEDGERNAME")
        if party and deemed_positive == "no":
            return party
    return _first_value(node, "PARTYLEDGERNAME", "LEDGERNAME")

def _party_gstin(node, party_name):
    for entry in [child for child in node.iter() if _tag(child) == "ALLLEDGERENTRIES.LIST"]:
        entry_party = _first_value(entry, "PARTYLEDGERNAME", "LEDGERNAME")
        if entry_party == party_name:
            value = _first_value(entry, "PARTYGSTIN", "GSTIN")
            if value:
                return value.upper()
    return (_first_value(node, "PARTYGSTIN", "GSTIN") or "").upper()

def _tax_breakdown(node):
    result = {"igst_amount": 0.0, "cgst_amount": 0.0, "sgst_amount": 0.0}
    for entry in [child for child in node.iter() if _tag(child) == "ALLLEDGERENTRIES.LIST"]:
        name = _first_value(entry, "LEDGERNAME", "PARTYLEDGERNAME").lower()
        amount = _amount(_first_value(entry, "AMOUNT"))
        if "igst" in name:
            result["igst_amount"] += amount
        elif "cgst" in name:
            result["cgst_amount"] += amount
        elif "sgst" in name:
            result["sgst_amount"] += amount
    return {key: round(value, 2) for key, value in result.items()}

def _party_amount(node, party_name):
    for entry in [child for child in node.iter() if _tag(child) == "ALLLEDGERENTRIES.LIST"]:
        if _first_value(entry, "PARTYLEDGERNAME", "LEDGERNAME") == party_name:
            return _amount(_first_value(entry, "AMOUNT"))
    return 0.0

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
    voucher_type = (values.get("VOUCHERTYPENAME") or values.get("VCHTYPE") or _text(node.attrib.get("VCHTYPE"))).lower()
    voucher_number = values.get("VOUCHERNUMBER") or _first_value(node, "VOUCHERNUMBER")
    voucher_date = values.get("DATE") or _first_value(node, "DATE")
    if not voucher_type or not voucher_number or voucher_type not in {"sales", "purchase", "receipt", "payment"}:
        return None
    allocations = _bill_allocations(node)
    allocation_amount = sum(item["amount"] for item in allocations)
    party_name = _purchase_or_sales_party(node) or "Tally Voucher"
    amount = allocation_amount or _party_amount(node, party_name) or sum(_amount(child.text) for child in node.iter() if _tag(child) == "AMOUNT")
    deemed_positive = values.get("ISDEEMEDPOSITIVE", "") or _first_value(node, "ISDEEMEDPOSITIVE")
    remote_id = values.get("REMOTEID") or values.get("GUID") or _first_value(node, "REMOTEID", "GUID") or None
    try:
        parsed_date = _date(voucher_date)
    except ValueError:
        return None
    tax = _tax_breakdown(node)
    return {"invoice_id": voucher_number, "remote_id": remote_id, "invoice_date": parsed_date, "total_amount": amount, "direction": _debit_credit(amount, deemed_positive), "voucher_type": voucher_type, "party_name": party_name, "party_gstin": _party_gstin(node, party_name), "taxable_value": round(max(amount - sum(tax.values()), 0), 2), **tax, "allocations": allocations}

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
    if found:
        if record.get("gstin"):
            client.table("cashflow_entities").update({"gstin": record["gstin"]}).eq("company_id", company_id).eq("id", found[0]["id"]).execute()
        return found[0]["id"]
    return (client.table("cashflow_entities").insert(payload).execute().data or [{}])[0].get("id")

def _save_purchase_bill(client, company_id, vendor_id, number, date_value, amount, voucher, identity):
    """Update an existing vendor bill or insert it without relying on a missing ON CONFLICT constraint."""
    existing = client.table("cashflow_bills").select("id").eq("company_id", company_id).eq("vendor_id", vendor_id).eq("bill_number", number).limit(1).execute().data or []
    tax_total = sum(float(voucher.get(key) or 0) for key in ("cgst_amount", "sgst_amount", "igst_amount"))
    payload = {"company_id": company_id, "vendor_id": vendor_id, "bill_number": number, "bill_date": date_value, "due_date": date_value, "payment_terms_days": 0, "amount": amount, "gst_amount": tax_total, "supplier_gstin": voucher.get("party_gstin") or None, "taxable_value": voucher.get("taxable_value"), "cgst_amount": voucher.get("cgst_amount", 0), "sgst_amount": voucher.get("sgst_amount", 0), "igst_amount": voucher.get("igst_amount", 0), "ocr_raw_data": {"source": "tally", "supplier_gstin": voucher.get("party_gstin"), "taxable_value": voucher.get("taxable_value"), "cgst_amount": voucher.get("cgst_amount", 0), "sgst_amount": voucher.get("sgst_amount", 0), "igst_amount": voucher.get("igst_amount", 0)}, "status": "pending", "created_by": identity.get("user_id")}
    if existing:
        return client.table("cashflow_bills").update(payload).eq("company_id", company_id).eq("id", existing[0]["id"]).execute()
    return client.table("cashflow_bills").insert(payload).execute()

def _dashboard(client, company_id):
    invoices = client.table("cashflow_invoices").select("amount,gst_amount").eq("company_id", company_id).in_("status", ["pending", "approved", "overdue"]).execute().data or []
    bills = client.table("cashflow_bills").select("amount,gst_amount").eq("company_id", company_id).in_("status", ["pending", "approved", "overdue"]).execute().data or []
    transactions = client.table("cashflow_transactions").select("amount,transaction_type").eq("company_id", company_id).execute().data or []
    inflow = sum(float(row.get("amount") or 0) for row in transactions if row.get("transaction_type") == "INFLOW")
    outflow = sum(float(row.get("amount") or 0) for row in transactions if row.get("transaction_type") == "OUTFLOW")
    invoice_ids = [row.get("id") for row in invoices if row.get("id")]
    payments = client.table("cashflow_transactions").select("invoice_id,amount").eq("company_id", company_id).in_("invoice_id", invoice_ids).execute().data or [] if invoice_ids else []
    paid_by_invoice = {}
    for payment in payments:
        paid_by_invoice[payment.get("invoice_id")] = paid_by_invoice.get(payment.get("invoice_id"), 0) + float(payment.get("amount") or 0)
    receivable = sum(max(float(row.get("amount") or 0) + float(row.get("gst_amount") or 0) - paid_by_invoice.get(row.get("id"), 0), 0) for row in invoices)
    return {"total_accounts_receivable": round(receivable, 2), "total_accounts_payable": round(sum(float(row.get("amount") or 0) + float(row.get("gst_amount") or 0) for row in bills), 2), "net_cash_flow": round(inflow - outflow, 2), "inflow": round(inflow, 2), "outflow": round(outflow, 2)}

def _import(req, auth):
    body = req.get_json()
    raw = base64.b64decode(body.get("file_content_base64", ""), validate=True)
    parsed = _parse_file(body.get("file_name", ""), raw)
    client = get_supabase_client(); company_id = auth["company_id"]; identity = auth.get("identity") or {}
    tenant_context = TenantContext(user_id=str(identity.get("user_id") or ""), company_id=company_id, role=str(identity.get("role") or ""), email=identity.get("email"), full_name=identity.get("full_name"))
    counts = {"imported": 0, "updated": 0, "skipped": 0, "errors": 0}
    errors = []
    duplicates = []
    entity_ids = {}
    ledger_gstins = {}
    for ledger in parsed["ledgers"]:
        entity_ids[(ledger["name"], ledger["entity_type"])] = _entity(client, company_id, ledger)
        if ledger.get("gstin"):
            ledger_gstins[(ledger["name"], ledger["entity_type"])] = ledger["gstin"]
    vouchers = sorted(
        parsed["vouchers"],
        key=lambda item: 0 if _text(item.get("voucher_type") or item.get("VOUCHERTYPENAME")).lower() in {"sales", "purchase"} else 1,
    )
    for voucher in vouchers:
        try:
            voucher_type = _text(voucher.get("voucher_type")).lower()
            number = _text(voucher.get("invoice_id") or voucher.get("VOUCHERNUMBER"))
            date_value = voucher.get("invoice_date") or _date(voucher.get("DATE"))
            amount = _amount(voucher.get("total_amount") or voucher.get("AMOUNT"))
            party = _text(voucher.get("party_name") or voucher.get("PARTYLEDGERNAME"))
            if voucher_type == "purchase" and not voucher.get("party_gstin"):
                voucher["party_gstin"] = ledger_gstins.get((party, "vendor"))
            if not number: counts["skipped"] += 1; continue
            source = {"company_id": company_id, "invoice_id": number, "remote_id": voucher.get("remote_id") or voucher.get("REMOTEID") or voucher.get("GUID"), "voucher_type": voucher_type, "voucher_date": date_value, "total_amount": amount, "direction": _debit_credit(amount, voucher.get("ISDEEMEDPOSITIVE")), "raw_data": voucher, "created_by": identity.get("user_id")}
            existing = []
            if source["remote_id"]:
                existing = client.table("cashflow_tally_records").select("id,invoice_id").eq("company_id", company_id).eq("remote_id", source["remote_id"]).limit(1).execute().data or []
            if not existing:
                existing = client.table("cashflow_tally_records").select("id,invoice_id").eq("company_id", company_id).eq("invoice_id", number).limit(1).execute().data or []
            if existing:
                client.table("cashflow_tally_records").update(source).eq("id", existing[0]["id"]).eq("company_id", company_id).execute()
                counts["updated"] += 1
                duplicates.append({"invoice_id": number, "remote_id": source["remote_id"], "reason": "REMOTEID" if source["remote_id"] else "invoice_id"})
            else:
                client.table("cashflow_tally_records").insert(source).execute(); counts["imported"] += 1
            if voucher_type in {"sales", "purchase"}:
                entity_type = "customer" if voucher_type == "sales" else "vendor"
                party_gstin = _text(voucher.get("party_gstin") or "").upper() or None
                entity_id = entity_ids.get((party, entity_type)) or _entity(client, company_id, {"name": party or "Tally Party", "entity_type": entity_type, "gstin": party_gstin, "gstin_status": "registered" if party_gstin and GSTIN_RE.fullmatch(party_gstin) else "unregistered"})
                if party_gstin:
                    client.table("cashflow_entities").update({"gstin": party_gstin}).eq("company_id", company_id).eq("id", entity_id).execute()
                if voucher_type == "purchase":
                    _save_purchase_bill(client, company_id, entity_id, number, date_value, amount, voucher, identity)
                else:
                    payload = {"company_id": company_id, "customer_id": entity_id, "invoice_number": number, "invoice_date": date_value, "due_date": date_value, "amount": amount, "gst_amount": 0, "status": "pending", "is_proforma": False, "created_by": identity.get("user_id")}
                    existing_invoice = client.table("cashflow_invoices").select("id").eq("company_id", company_id).eq("invoice_number", number).limit(1).execute().data or []
                    if existing_invoice:
                        client.table("cashflow_invoices").update(payload).eq("company_id", company_id).eq("id", existing_invoice[0]["id"]).execute()
                    else:
                        client.table("cashflow_invoices").insert(payload).execute()
            elif voucher_type in {"receipt", "payment"}:
                transaction_type = "INFLOW" if voucher_type == "receipt" else "OUTFLOW"
                allocations = voucher.get("allocations") or []
                if not allocations:
                    allocations = [{"reference": None, "amount": amount}]
                for allocation in allocations:
                    reference = _text(allocation.get("reference"))
                    linked_invoice_id = None
                    linked_bill_id = None
                    if reference:
                        linked_invoices = client.table("cashflow_invoices").select("id").eq("company_id", company_id).eq("invoice_number", reference).limit(1).execute().data or []
                        linked_bills = client.table("cashflow_bills").select("id").eq("company_id", company_id).eq("bill_number", reference).limit(1).execute().data or []
                        linked_invoice_id = linked_invoices[0]["id"] if linked_invoices else None
                        linked_bill_id = linked_bills[0]["id"] if linked_bills else None
                    payment_amount = _amount(allocation.get("amount")) or amount
                    existing_payment_query = client.table("cashflow_transactions").select("id").eq("company_id", company_id).eq("payment_mode", "tally")
                    if source["remote_id"]:
                        existing_payment_query = existing_payment_query.eq("tally_remote_id", source["remote_id"])
                    else:
                        existing_payment_query = existing_payment_query.eq("tally_voucher_number", number)
                    if linked_invoice_id:
                        existing_payment_query = existing_payment_query.eq("invoice_id", linked_invoice_id)
                    else:
                        existing_payment_query = existing_payment_query.is_("invoice_id", "null")
                    if linked_bill_id:
                        existing_payment_query = existing_payment_query.eq("bill_id", linked_bill_id)
                    else:
                        existing_payment_query = existing_payment_query.is_("bill_id", "null")
                    existing_payment = existing_payment_query.limit(1).execute().data or []
                    payment_payload = {"company_id": company_id, "transaction_date": date_value, "amount": payment_amount, "transaction_type": transaction_type, "payment_mode": "tally", "reference_no": number, "tally_voucher_number": number, "tally_remote_id": source["remote_id"], "category": "Cash Collected" if voucher_type == "receipt" else "Cash Disbursed", "created_by": identity.get("user_id"), "invoice_id": linked_invoice_id, "bill_id": linked_bill_id}
                    if existing_payment:
                        client.table("cashflow_transactions").update(payment_payload).eq("company_id", company_id).eq("id", existing_payment[0]["id"]).execute()
                    else:
                        client.table("cashflow_transactions").insert(payment_payload).execute()
        except Exception as error:
            counts["errors"] += 1
            voucher_number = _text(voucher.get("invoice_id") or voucher.get("VOUCHERNUMBER") or "unknown")
            detail = {"voucherNo": voucher_number, "voucherType": _text(voucher.get("voucher_type") or "unknown"), "error": str(error)}
            errors.append(detail)
            LOGGER.exception("[Tally Import Error] Voucher %s failed: %s", voucher_number, error)
    audit.record(client, tenant_context, "upload", "tally_import", None, "success", {"counts": counts, "duplicates": duplicates})
    return _json_response({"ok": True, "data": {**counts, "errors": errors, "duplicates": duplicates, "dashboard": _dashboard(client, company_id)}})

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
