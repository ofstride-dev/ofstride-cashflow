import io
import json
import logging
import os
import uuid
from datetime import datetime
from decimal import Decimal

import azure.functions as func
import pandas as pd

from shared.admin_auth import require_cashflow_tenant
from shared.db import get_supabase_client


def _err(status_code: int, message: str, trace_id: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"success": False, "error": message, "trace_id": trace_id}),
        mimetype="application/json",
        status_code=status_code,
    )


def _num(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_iso_date(value: str) -> datetime.date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _state_code(gstin: str | None) -> str:
    normalized = str(gstin or "").strip()
    if len(normalized) >= 2 and normalized[:2].isdigit():
        return normalized[:2]
    return ""


def _split_tax(total_gst: float, seller_gstin: str | None, buyer_gstin: str | None) -> dict:
    total = round(max(total_gst, 0.0), 2)
    if total <= 0:
        return {"igst": 0.0, "cgst": 0.0, "sgst": 0.0}

    seller_state = _state_code(seller_gstin)
    buyer_state = _state_code(buyer_gstin)

    if seller_state and buyer_state and seller_state == buyer_state:
        half = round(total / 2, 2)
        return {
            "igst": 0.0,
            "cgst": half,
            "sgst": round(total - half, 2),
        }

    return {"igst": total, "cgst": 0.0, "sgst": 0.0}


def main(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = str(uuid.uuid4())

    auth = require_cashflow_tenant(req)
    if not auth.get("ok"):
        return _err(auth.get("status_code", 401), auth.get("error") or "Unauthorized", trace_id)
    identity = auth.get("identity") or {}
    company_id = str(identity.get("company_id") or "").strip()
    if not company_id:
        return _err(403, "Complete workspace onboarding before exporting GST reports", trace_id)

    start_date = str(req.params.get("start_date") or "").strip()
    end_date = str(req.params.get("end_date") or "").strip()

    if not start_date or not end_date:
        return _err(400, "start_date and end_date are required (YYYY-MM-DD)", trace_id)

    try:
        start_dt = _parse_iso_date(start_date)
        end_dt = _parse_iso_date(end_date)
    except ValueError:
        return _err(400, "Invalid date format. Use YYYY-MM-DD", trace_id)

    if start_dt > end_dt:
        return _err(400, "start_date cannot be later than end_date", trace_id)

    try:
        supabase = get_supabase_client()
        company_gstin = (
            req.params.get("company_gstin")
            or os.environ.get("COMPANY_GSTIN")
            or os.environ.get("CASHFLOW_COMPANY_GSTIN")
            or ""
        )

        invoices_res = (
            supabase.table("cashflow_invoices")
            .select("*, cashflow_entities!cashflow_invoices_customer_id_fkey(id,name,gstin)")
            .eq("company_id", company_id)
            .in_("status", ["approved", "paid"])
            .eq("is_proforma", False)
            .gte("invoice_date", start_date)
            .lte("invoice_date", end_date)
            .order("invoice_date", desc=False)
            .execute()
        )

        bills_res = (
            supabase.table("cashflow_bills")
            .select("*, cashflow_entities!cashflow_bills_vendor_id_fkey(id,name,gstin)")
            .eq("company_id", company_id)
            .in_("status", ["approved", "paid"])
            .gte("bill_date", start_date)
            .lte("bill_date", end_date)
            .order("bill_date", desc=False)
            .execute()
        )

        gstr1_rows = []
        gstr1_source_rows = []
        warnings = []
        outward_taxable = 0.0
        outward_igst = 0.0
        outward_cgst = 0.0
        outward_sgst = 0.0

        for inv in invoices_res.data or []:
            customer = inv.get("cashflow_entities") or {}
            customer_gstin = str(customer.get("gstin") or "")
            customer_name = str(customer.get("name") or "")

            amount = _num(inv.get("amount"))
            gst_amount = _num(inv.get("gst_amount"))
            taxable_value = round(max(amount - gst_amount, 0.0), 2)

            split = _split_tax(gst_amount, company_gstin, customer_gstin)
            place_of_supply = _state_code(customer_gstin)

            gstr1_rows.append(
                {
                    "GSTIN/UIN of Recipient": customer_gstin,
                    "Receiver Name": customer_name,
                    "Invoice Number": inv.get("invoice_number"),
                    "Invoice Date": inv.get("invoice_date"),
                    "Invoice Value": round(amount, 2),
                    "Place Of Supply": place_of_supply,
                    "Reverse Charge": "N",
                    "Invoice Type": "Regular B2B",
                    "Taxable Value": taxable_value,
                    "Integrated Tax": split["igst"],
                    "Central Tax": split["cgst"],
                    "State/UT Tax": split["sgst"],
                }
            )

            gstr1_source_rows.append(
                {
                    "Invoice ID": str(inv.get("id") or ""),
                    "Invoice Number": inv.get("invoice_number"),
                    "Invoice Date": inv.get("invoice_date"),
                    "Customer": customer_name,
                    "Customer GSTIN": customer_gstin,
                    "Status": inv.get("status"),
                    "Invoice Value": round(amount, 2),
                    "GST Amount": round(gst_amount, 2),
                    "Taxable Value": taxable_value,
                    "IGST": split["igst"],
                    "CGST": split["cgst"],
                    "SGST": split["sgst"],
                }
            )

            if not str(inv.get("invoice_number") or "").strip():
                warnings.append(
                    {
                        "Section": "AR",
                        "Reference": str(inv.get("id") or ""),
                        "Issue": "Missing invoice number",
                    }
                )
            if amount <= 0:
                warnings.append(
                    {
                        "Section": "AR",
                        "Reference": str(inv.get("invoice_number") or inv.get("id") or ""),
                        "Issue": "Invoice amount is zero or negative",
                    }
                )
            if gst_amount > amount and amount > 0:
                warnings.append(
                    {
                        "Section": "AR",
                        "Reference": str(inv.get("invoice_number") or inv.get("id") or ""),
                        "Issue": "GST exceeds invoice amount",
                    }
                )
            if customer_gstin and len(customer_gstin) != 15:
                warnings.append(
                    {
                        "Section": "AR",
                        "Reference": str(inv.get("invoice_number") or inv.get("id") or ""),
                        "Issue": "Customer GSTIN length is not 15",
                    }
                )

            outward_taxable += taxable_value
            outward_igst += split["igst"]
            outward_cgst += split["cgst"]
            outward_sgst += split["sgst"]

        itc_taxable = 0.0
        itc_igst = 0.0
        itc_cgst = 0.0
        itc_sgst = 0.0
        itc_source_rows = []

        for bill in bills_res.data or []:
            vendor = bill.get("cashflow_entities") or {}
            vendor_gstin = str(vendor.get("gstin") or "")

            amount = _num(bill.get("amount"))
            gst_amount = _num(bill.get("gst_amount"))
            taxable_value = round(max(amount - gst_amount, 0.0), 2)

            split = _split_tax(gst_amount, vendor_gstin, company_gstin)

            itc_taxable += taxable_value
            itc_igst += split["igst"]
            itc_cgst += split["cgst"]
            itc_sgst += split["sgst"]

            itc_source_rows.append(
                {
                    "Bill ID": str(bill.get("id") or ""),
                    "Bill Number": bill.get("bill_number"),
                    "Bill Date": bill.get("bill_date"),
                    "Vendor": str(vendor.get("name") or ""),
                    "Vendor GSTIN": vendor_gstin,
                    "Status": bill.get("status"),
                    "Bill Value": round(amount, 2),
                    "GST Amount": round(gst_amount, 2),
                    "Taxable Value": taxable_value,
                    "ITC IGST": split["igst"],
                    "ITC CGST": split["cgst"],
                    "ITC SGST": split["sgst"],
                }
            )

            if not str(bill.get("bill_number") or "").strip():
                warnings.append(
                    {
                        "Section": "AP",
                        "Reference": str(bill.get("id") or ""),
                        "Issue": "Missing bill number",
                    }
                )
            if amount <= 0:
                warnings.append(
                    {
                        "Section": "AP",
                        "Reference": str(bill.get("bill_number") or bill.get("id") or ""),
                        "Issue": "Bill amount is zero or negative",
                    }
                )
            if gst_amount > amount and amount > 0:
                warnings.append(
                    {
                        "Section": "AP",
                        "Reference": str(bill.get("bill_number") or bill.get("id") or ""),
                        "Issue": "GST exceeds bill amount",
                    }
                )
            if vendor_gstin and len(vendor_gstin) != 15:
                warnings.append(
                    {
                        "Section": "AP",
                        "Reference": str(bill.get("bill_number") or bill.get("id") or ""),
                        "Issue": "Vendor GSTIN length is not 15",
                    }
                )

        net_igst = round(outward_igst - itc_igst, 2)
        net_cgst = round(outward_cgst - itc_cgst, 2)
        net_sgst = round(outward_sgst - itc_sgst, 2)

        gstr3b_rows = [
            {
                "Section": "Table 3.1 Outward Taxable Supplies",
                "Taxable Value": round(outward_taxable, 2),
                "IGST": round(outward_igst, 2),
                "CGST": round(outward_cgst, 2),
                "SGST": round(outward_sgst, 2),
                "Net Tax Liability": round(outward_igst + outward_cgst + outward_sgst, 2),
            },
            {
                "Section": "Table 4 Eligible ITC",
                "Taxable Value": round(itc_taxable, 2),
                "IGST": round(itc_igst, 2),
                "CGST": round(itc_cgst, 2),
                "SGST": round(itc_sgst, 2),
                "Net Tax Liability": round(-(itc_igst + itc_cgst + itc_sgst), 2),
            },
            {
                "Section": "Net Payable (3.1 - 4)",
                "Taxable Value": round(outward_taxable - itc_taxable, 2),
                "IGST": net_igst,
                "CGST": net_cgst,
                "SGST": net_sgst,
                "Net Tax Liability": round(net_igst + net_cgst + net_sgst, 2),
            },
        ]

        gstr1_df = pd.DataFrame(gstr1_rows)
        if gstr1_df.empty:
            gstr1_df = pd.DataFrame(
                columns=[
                    "GSTIN/UIN of Recipient",
                    "Receiver Name",
                    "Invoice Number",
                    "Invoice Date",
                    "Invoice Value",
                    "Place Of Supply",
                    "Reverse Charge",
                    "Invoice Type",
                    "Taxable Value",
                    "Integrated Tax",
                    "Central Tax",
                    "State/UT Tax",
                ]
            )

        gstr3b_df = pd.DataFrame(gstr3b_rows)
        gstr1_source_df = pd.DataFrame(gstr1_source_rows)
        itc_source_df = pd.DataFrame(itc_source_rows)
        warnings_df = pd.DataFrame(warnings) if warnings else pd.DataFrame(columns=["Section", "Reference", "Issue"])

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            gstr1_df.to_excel(writer, sheet_name="GSTR-1 B2B", index=False)
            gstr3b_df.to_excel(writer, sheet_name="GSTR-3B Summary", index=False)
            gstr1_source_df.to_excel(writer, sheet_name="AR Source Details", index=False)
            itc_source_df.to_excel(writer, sheet_name="AP ITC Source", index=False)
            warnings_df.to_excel(writer, sheet_name="Validation Warnings", index=False)

        filename = f"gstr_export_{start_date}_to_{end_date}.xlsx"
        return func.HttpResponse(
            body=output.getvalue(),
            status_code=200,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Trace-Id": trace_id,
            },
        )
    except Exception as exc:
        logging.error(f"GSTR export failed: {str(exc)}")
        return _err(500, str(exc), trace_id)
