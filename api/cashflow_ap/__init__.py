import azure.functions as func
import json
import logging
import os
import base64
import re
from datetime import datetime, timedelta
from shared.db import get_supabase_client
from shared.tax_engine_interface import calculate_tds, calculate_msme_due_date
from shared.admin_auth import identity_can_approve, identity_can_use_cashflow, require_cashflow_tenant, resolve_identity_headers
from cashflow.ap import APRepository
from shared.dedup import document_fingerprint, duplicate_key, normalize_invoice_number
from shared.tenant import audit, TenantContext


def _safe_json(data) -> str:
    """Serialize AP responses without allowing duplicate details to crash the handler."""
    try:
        return json.dumps(data, default=str)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "Response serialization failed"})


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.replace(',', '').strip()
            if not normalized:
                return default
            return float(normalized)
        return float(value)
    except (TypeError, ValueError):
        return default


def _field_amount(field) -> float | None:
    if field is None:
        return None

    value = getattr(field, "value", None)
    if value is None:
        return None

    amount_obj = getattr(value, "amount", None)
    if amount_obj is not None:
        return _safe_float(amount_obj, None)

    if isinstance(value, (int, float, str)):
        return _safe_float(value, None)

    return None


def _extract_first_amount(fields: dict, keys: list[str]) -> float | None:
    for key in keys:
        candidate = _field_amount(fields.get(key))
        if candidate is not None:
            return candidate
    return None


def _field_text(field, default: str = "") -> str:
    value = getattr(field, "value", None) if field is not None else None
    if value is None:
        return default
    return str(value).strip()


def _extract_line_items(fields: dict) -> list[dict]:
    items_field = fields.get("Items") or fields.get("items")
    raw_items = getattr(items_field, "value", None) if items_field is not None else None
    if not isinstance(raw_items, list):
        raw_items = getattr(items_field, "value_array", None) if items_field is not None else None
    if not isinstance(raw_items, list):
        return []

    parsed_items = []
    for item in raw_items:
        item_fields = getattr(item, "value", None)
        if not isinstance(item_fields, dict):
            item_fields = getattr(item, "value_object", None)
        if not isinstance(item_fields, dict):
            continue

        description = _field_text(item_fields.get("Description"))
        quantity = _field_amount(item_fields.get("Quantity"))
        unit_price = _field_amount(item_fields.get("Price"))
        total_price = _field_amount(item_fields.get("TotalPrice"))
        quantity = quantity if quantity is not None and quantity > 0 else 1.0
        unit_price = unit_price if unit_price is not None else 0.0
        total_price = total_price if total_price is not None else unit_price * quantity

        if not description and unit_price == 0 and total_price == 0:
            continue

        parsed_items.append({
            "itemName": description,
            "description": description,
            "unitPrice": round(unit_price, 3),
            "quantity": round(quantity, 3),
            "discount": 0.0,
            "lineTotal": round(total_price, 3),
        })

    return parsed_items


def _extract_gst_from_content(content: str) -> float:
    if not content:
        return 0.0

    total = 0.0

    # Pattern 1: CGST@2.5% : 22.49 (or SGST/IGST variants)
    pattern_rate_then_amount = re.compile(
        r"(?:cgst|sgst|igst)\s*@?\s*\d+(?:\.\d+)?\s*%\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?)",
        flags=re.IGNORECASE,
    )
    for match in pattern_rate_then_amount.finditer(content):
        total += _safe_float(match.group(1), 0.0)

    # Pattern 2: CGST : 22.49 (without explicit rate)
    if total <= 0:
        pattern_label_then_amount = re.compile(
            r"(?:cgst|sgst|igst)\b[^0-9%]{0,12}([0-9]+(?:\.[0-9]+)?)",
            flags=re.IGNORECASE,
        )
        for match in pattern_label_then_amount.finditer(content):
            total += _safe_float(match.group(1), 0.0)

    return round(total, 2)

def _decode_upload_bytes(raw_file_value) -> bytes:
    if not isinstance(raw_file_value, str) or not raw_file_value.strip():
        raise ValueError("No file provided")

    payload = raw_file_value.strip()
    if "," in payload:
        payload = payload.split(",", 1)[1]

    try:
        return base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError(f"Invalid file payload: {str(exc)}")


def _classify_ocr_error(exc: Exception) -> tuple[str, str]:
    msg = str(exc or "")
    lower = msg.lower()

    if "invalidcontent" in lower or "format is unsupported" in lower or "file is corrupted" in lower:
        return (
            "warning",
            "Document Intelligence could not read this file content. Please upload a clearer PDF/image (not encrypted/password-protected).",
        )

    if "unauthorized" in lower or "forbidden" in lower or "401" in lower or "403" in lower:
        return (
            "error",
            "OCR authentication failed. Verify AZURE_DOC_INTEL_ENDPOINT and AZURE_DOC_INTEL_KEY in Azure Function App settings.",
        )

    if "modulenotfounderror" in lower or "no module named" in lower:
        return (
            "error",
            "OCR runtime dependency is missing on the Function host. Redeploy with azure-ai-formrecognizer in requirements.",
        )

    if "resourcenotfound" in lower or "404" in lower:
        return (
            "error",
            "OCR endpoint/model was not found. Verify the endpoint region and service resource.",
        )

    return (
        "warning",
        "OCR service error. Please retry with a clearer file or verify OCR configuration.",
    )


def _normalize_ap_extracted(extracted: dict) -> dict:
    amount_before_gst = round(_safe_float(extracted.get("amount_before_gst"), 0.0), 3)
    gst_amount = round(_safe_float(extracted.get("gst_amount"), 0.0), 3)
    total_amount = round(_safe_float(extracted.get("total_amount"), _safe_float(extracted.get("amount"), 0.0)), 3)
    if total_amount <= 0 and (amount_before_gst > 0 or gst_amount > 0):
        total_amount = round(amount_before_gst + gst_amount, 3)
    if amount_before_gst <= 0 and total_amount > 0:
        amount_before_gst = round(max(total_amount - gst_amount, 0.0), 3)

    return {
        "vendor_name": str(extracted.get("vendor_name") or "").strip(),
        "vendor_gstin": str(extracted.get("vendor_gstin") or "").strip(),
        "bill_number": str(extracted.get("bill_number") or "").strip(),
        "bill_date": str(extracted.get("bill_date") or datetime.now().strftime("%Y-%m-%d")),
        "amount_before_gst": amount_before_gst,
        "gst_amount": gst_amount,
        "total_amount": total_amount,
        # Keep backward-compatible key used by save flow.
        "amount": total_amount,
        "parsedLineItems": extracted.get("parsedLineItems") if isinstance(extracted.get("parsedLineItems"), list) else [],
    }


def _validate_ap_extracted(extracted: dict) -> list[str]:
    issues: list[str] = []
    if extracted.get("amount", 0.0) <= 0:
        issues.append("amount_missing_or_zero")
    if not str(extracted.get("bill_number") or "").strip():
        issues.append("bill_number_missing")
    bill_date = str(extracted.get("bill_date") or "").strip()
    try:
        datetime.fromisoformat(bill_date)
    except ValueError:
        issues.append("bill_date_invalid")
    return issues


def _repair_ap_extracted(extracted: dict, ocr_content: str = "") -> dict:
    repaired = dict(extracted)
    if repaired.get("gst_amount", 0.0) <= 0:
        repaired["gst_amount"] = round(_extract_gst_from_content(ocr_content or ""), 2)

    if repaired.get("amount", 0.0) <= 0 and repaired.get("gst_amount", 0.0) > 0:
        # Conservative fallback: keep total amount at least equal to tax until user review.
        repaired["amount"] = repaired["gst_amount"]

    if not str(repaired.get("bill_number") or "").strip():
        repaired["bill_number"] = f"OCR-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    return _normalize_ap_extracted(repaired)


def _build_ap_extracted_from_doc(fields: dict, ocr_content: str) -> dict:
    total_tax = _extract_first_amount(fields, ["TotalTax", "Tax", "TaxTotal"])
    subtotal = _extract_first_amount(fields, ["SubTotal", "Subtotal"])
    invoice_total = _extract_first_amount(fields, ["InvoiceTotal", "TotalAmount", "AmountDue", "Total"])
    parsed_tax_from_content = _extract_gst_from_content(ocr_content or "")

    if total_tax is None:
        total_tax = parsed_tax_from_content
    elif parsed_tax_from_content > 0 and total_tax > 0 and parsed_tax_from_content > (total_tax * 1.5):
        total_tax = parsed_tax_from_content

    if invoice_total is None:
        if subtotal is not None and total_tax is not None:
            invoice_total = round(subtotal + total_tax, 2)
        elif subtotal is not None:
            invoice_total = subtotal
        else:
            invoice_total = 0.0

    if total_tax is None:
        total_tax = 0.0

    extracted = {
        "vendor_name": _field_text(fields.get("VendorName") or fields.get("MerchantName")),
        "vendor_gstin": (fields.get("VendorTaxId").value if fields.get("VendorTaxId") else "") or "",
        "bill_number": _field_text(fields.get("InvoiceId") or fields.get("ReceiptId")),
        "bill_date": _field_text(fields.get("InvoiceDate") or fields.get("TransactionDate"), datetime.now().strftime("%Y-%m-%d")),
        "amount_before_gst": round(_safe_float(subtotal, 0.0), 2),
        "total_amount": round(_safe_float(invoice_total, 0.0), 2),
        "amount": round(_safe_float(invoice_total, 0.0), 2),
        "gst_amount": round(_safe_float(total_tax, 0.0), 2),
        "parsedLineItems": _extract_line_items(fields),
    }
    return _normalize_ap_extracted(extracted)


def _run_ap_ocr_pipeline(file_bytes: bytes, endpoint: str, key: str, model_id: str = "prebuilt-receipt") -> dict:
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.formrecognizer import DocumentAnalysisClient

    client = DocumentAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    poller = client.begin_analyze_document(model_id, document=file_bytes)
    ocr_result = poller.result()
    if not ocr_result.documents:
        return {
            "extracted": _normalize_ap_extracted({
                "vendor_name": "",
                "vendor_gstin": "",
                "bill_number": "",
                "bill_date": datetime.now().strftime("%Y-%m-%d"),
                "amount": 0.0,
                "gst_amount": 0.0,
            }),
            "pipeline": {
                "stage": "validate",
                "passes": 1,
                "issues": ["no_documents_detected"],
            },
        }

    doc = ocr_result.documents[0]
    fields = doc.fields or {}
    ocr_content = getattr(ocr_result, "content", "") or ""

    extracted = _build_ap_extracted_from_doc(fields, ocr_content)
    pipeline_passes = []
    max_passes = 2

    for pass_index in range(max_passes):
        issues = _validate_ap_extracted(extracted)
        pipeline_passes.append({
            "pass": pass_index + 1,
            "issues": issues,
            "amount": extracted.get("amount", 0.0),
            "gst_amount": extracted.get("gst_amount", 0.0),
        })
        if not issues:
            break
        extracted = _repair_ap_extracted(extracted, ocr_content)

    final_issues = pipeline_passes[-1]["issues"] if pipeline_passes else []
    return {
        "extracted": extracted,
        "pipeline": {
            "stage": "complete",
            "passes": len(pipeline_passes),
            "issues": final_issues,
            "pass_details": pipeline_passes,
        },
    }

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing Accounts Payable request.')
    action = req.route_params.get("action")
    if not action and req.method == "GET":
        action = "list"

    auth = require_cashflow_tenant(req)
    if not auth["ok"]:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": auth["error"]}),
            mimetype="application/json",
            status_code=auth["status_code"],
        )

    identity = auth.get("identity") or {}
    company_id = str(identity.get("company_id") or "").strip()
    if not company_id and action != "ocr":
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "Complete workspace onboarding before using Accounts Payable."}),
            mimetype="application/json",
            status_code=403,
        )
    
    try:
        supabase = get_supabase_client()
        tenant_context = TenantContext(user_id=str(identity.get("user_id") or ""), company_id=company_id, role=str(identity.get("role") or ""), email=identity.get("email"), full_name=identity.get("full_name"))

        def build_mock_extracted(reason: str = "OCR could not extract fields") -> dict:
            # Keep endpoint contract stable when OCR can't infer fields.
            return {
                "vendor_name": "",
                "vendor_gstin": "",
                "bill_number": "",
                "bill_date": datetime.now().strftime("%Y-%m-%d"),
                "amount": 0.0,
                "gst_amount": 0.0,
                "_scan_status": "warning",
                "_scan_message": reason,
            }

        def has_meaningful_scan(extracted: dict) -> bool:
            if not isinstance(extracted, dict):
                return False
            return any(
                [
                    str(extracted.get("vendor_name") or "").strip(),
                    str(extracted.get("vendor_gstin") or "").strip(),
                    str(extracted.get("bill_number") or "").strip(),
                    float(_safe_float(extracted.get("amount"), 0.0)) > 0,
                    float(_safe_float(extracted.get("gst_amount"), 0.0)) > 0,
                ]
            )

        if req.method == "GET" and action == "list":
            auth = require_cashflow_tenant(req)
            if not auth["ok"]:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": auth["error"]}),
                    mimetype="application/json",
                    status_code=auth["status_code"],
                )
            identity = auth.get("identity") or {}
            company_id = str(identity.get("company_id") or "").strip()
            if not company_id:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Complete workspace onboarding before using Accounts Payable."}),
                    mimetype="application/json",
                    status_code=403,
                )

        # 1. GET /api/cashflow/ap/list
        if req.method == "GET" and action == "list":
            try:
                response = APRepository(supabase).list_bills(auth["tenant"])
            except Exception as list_error:
                # Cashflow tables not migrated yet — return an empty list.
                return func.HttpResponse(json.dumps({"ok": True, "data": []}), mimetype="application/json")

            return func.HttpResponse(json.dumps({"ok": True, "data": response.data}), mimetype="application/json")

        if req.method == "POST" and action in {"update", "delete", "void"}:
            if not identity_can_approve(identity):
                return func.HttpResponse(json.dumps({"ok": False, "error": "Only owners, admins, or finance users can modify AP records."}), mimetype="application/json", status_code=403)
            data = req.get_json()
            bill_id = str(data.get("bill_id") or "").strip()
            reason = str(data.get("reason") or "").strip()
            comment = str(data.get("comment") or "").strip()
            if not bill_id or not reason or (reason == "Other" and not comment):
                return func.HttpResponse(json.dumps({"ok": False, "error": "bill_id and a mandatory reason are required."}), mimetype="application/json", status_code=400)
            current = supabase.table("cashflow_bills").select("*").eq("company_id", company_id).eq("id", bill_id).limit(1).execute().data or []
            if not current:
                return func.HttpResponse(json.dumps({"ok": False, "error": "Bill not found."}), mimetype="application/json", status_code=404)
            record = current[0]
            if action == "delete":
                audit.record(supabase, tenant_context, "delete", "cashflow_bill", bill_id, "success", {"reason": reason, "comment": comment, "record": record})
                supabase.table("cashflow_transactions").delete().eq("company_id", company_id).eq("bill_id", bill_id).execute()
                supabase.table("expenses").update({"ap_bill_id": None}).eq("company_id", company_id).eq("ap_bill_id", bill_id).execute()
                supabase.table("cashflow_bills").delete().eq("company_id", company_id).eq("id", bill_id).execute()
                return func.HttpResponse(json.dumps({"ok": True, "data": {"id": bill_id, "deleted": True}}), mimetype="application/json")
            if action == "void":
                updated = supabase.table("cashflow_bills").update({"status": "cancelled"}).eq("company_id", company_id).eq("id", bill_id).execute()
                audit.record(supabase, tenant_context, "void", "cashflow_bill", bill_id, "success", {"reason": reason, "comment": comment, "record": record})
                return func.HttpResponse(json.dumps({"ok": True, "data": (updated.data or [record])[0]}), mimetype="application/json")
            allowed = {key: data[key] for key in ("bill_number", "bill_date", "due_date", "payment_terms_days", "amount", "gst_amount", "tds_amount", "line_items", "party_details") if key in data}
            if not allowed:
                return func.HttpResponse(json.dumps({"ok": False, "error": "No editable bill fields were provided."}), mimetype="application/json", status_code=400)
            updated = supabase.table("cashflow_bills").update(allowed).eq("company_id", company_id).eq("id", bill_id).execute()
            audit.record(supabase, tenant_context, "edit", "cashflow_bill", bill_id, "success", {"reason": reason, "comment": comment, "changes": allowed})
            return func.HttpResponse(json.dumps({"ok": True, "data": (updated.data or [record])[0]}), mimetype="application/json")

        # 2. POST /api/cashflow/ap/ocr
        elif req.method == "POST" and action == "ocr":
            auth = resolve_identity_headers(req, allow_anonymous=True)
            req_body = req.get_json()
            if not isinstance(req_body, dict):
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Invalid JSON object"}),
                    mimetype="application/json",
                    status_code=400,
                )

            b64_file = req_body.get("file")
            try:
                file_bytes = _decode_upload_bytes(b64_file)
            except ValueError as exc:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": str(exc)}),
                    mimetype="application/json",
                    status_code=400,
                )

            # Mock fallback if Azure Doc Intel keys aren't set yet
            endpoint = os.environ.get("AZURE_DOC_INTEL_ENDPOINT")
            key = os.environ.get("AZURE_DOC_INTEL_KEY")

            if endpoint and key:
                try:
                    model_id = os.environ.get("AZURE_DOC_INTEL_MODEL", "prebuilt-receipt")
                    pipeline_result = _run_ap_ocr_pipeline(file_bytes, endpoint, key, model_id)
                    extracted = _normalize_ap_extracted(pipeline_result.get("extracted") or {})
                    final_issues = (pipeline_result.get("pipeline") or {}).get("issues") or []
                    if final_issues:
                        extracted["_scan_status"] = "warning"
                        extracted["_scan_message"] = "Invoice parsed with validation warnings. Please review before save."
                    else:
                        extracted["_scan_status"] = "success"
                        extracted["_scan_message"] = "Invoice parsed and validated successfully."
                    extracted["_pipeline"] = pipeline_result.get("pipeline") or {}
                    if not has_meaningful_scan(extracted):
                        fallback = build_mock_extracted("Invoice scanned, but fields were not extracted. Please review file quality or format.")
                        fallback["_pipeline"] = extracted.get("_pipeline")
                        extracted = fallback
                except Exception as ocr_error:
                    logging.warning(f"AP OCR fallback triggered: {str(ocr_error)}")
                    error_status, error_message = _classify_ocr_error(ocr_error)
                    extracted = build_mock_extracted(error_message)
                    extracted["_scan_status"] = error_status
                    if str(os.environ.get("ENV") or "").lower() == "dev":
                        extracted["_scan_error_detail"] = str(ocr_error)[:280]
            else:
                # Local dev fallback when Azure credentials are pending
                extracted = build_mock_extracted(
                    "OCR is not configured. Set AZURE_DOC_INTEL_ENDPOINT and AZURE_DOC_INTEL_KEY in Function settings."
                )
            
            return func.HttpResponse(json.dumps({"ok": True, "data": extracted}), mimetype="application/json")

        # 3. POST /api/cashflow/ap/save
        elif req.method == "POST" and action == "save":
            auth = require_cashflow_tenant(req)
            if not auth["ok"]:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": auth["error"]}),
                    mimetype="application/json",
                    status_code=auth["status_code"],
                )
            identity = auth.get("identity") or {}
            company_id = str(identity.get("company_id") or "").strip()
            if not identity_can_use_cashflow(identity):
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Cashflow access requires membership in a company workspace."}),
                    mimetype="application/json",
                    status_code=403,
                )
            data = req.get_json()
            vendor_id = APRepository(supabase).get_or_create_vendor(auth["tenant"], data.get("vendor_name"), data.get("vendor_gstin"))
            line_items = data.get("line_items") if isinstance(data.get("line_items"), list) else []
            party_details = data.get("party_details") if isinstance(data.get("party_details"), dict) else {}

            amount = float(data.get("total_amount", data.get("amount", 0)))
            amount_before_gst = float(data.get("amount_before_gst", max(amount - float(data.get("gst_amount", 0)), 0)))
            gst_rate = max(0.0, min(100.0, float(data.get("gst_rate", 0) or 0)))
            gst_amount = round(amount_before_gst * gst_rate / 100, 2) if data.get("gst_rate") not in (None, "") else float(data.get("gst_amount", 0))
            amount = round(amount_before_gst + gst_amount, 2)
            tds_section = data.get("tds_section", "NONE")
            # TDS should apply on taxable value (before GST) where possible.
            tds_amount = calculate_tds(amount_before_gst if amount_before_gst > 0 else amount, tds_section)

            bill_date = data.get("bill_date") or datetime.now().strftime("%Y-%m-%d")
            try:
                payment_terms_days = int(data.get("payment_terms_days", 30))
                if payment_terms_days < 0:
                    raise ValueError
            except (TypeError, ValueError):
                return func.HttpResponse(json.dumps({"ok": False, "error": "payment_terms_days must be a non-negative integer"}), mimetype="application/json", status_code=400)
            due_date = (datetime.strptime(bill_date, "%Y-%m-%d") + timedelta(days=payment_terms_days)).strftime("%Y-%m-%d")

            supplied_bill_number = str(data.get("bill_number") or "").strip()
            dedup_fingerprint = document_fingerprint(
                party_id=vendor_id,
                party_name=data.get("vendor_name"),
                document_date=bill_date,
                amount=amount,
                gst_amount=0,
                line_items=line_items,
            )
            normalized_bill_number, dedup_fingerprint = duplicate_key(supplied_bill_number, dedup_fingerprint)
            force_save = bool(data.get("force_save"))
            duplicate_query = supabase.table("cashflow_bills").select("id,bill_number,bill_date,amount,gst_amount,cashflow_entities(name)").eq("company_id", company_id).eq("vendor_id", vendor_id).limit(1)
            if normalized_bill_number:
                duplicate_query = duplicate_query.eq("normalized_bill_number", normalized_bill_number)
            else:
                duplicate_query = duplicate_query.eq("dedup_fingerprint", dedup_fingerprint)
            try:
                duplicate_rows = duplicate_query.execute().data or []
            except Exception as duplicate_error:
                # Keep duplicate warnings usable while an older deployment is
                # waiting for the additive dedup migration.
                if "column" not in str(duplicate_error).lower():
                    raise
                legacy_rows = supabase.table("cashflow_bills").select("id,bill_number,bill_date,amount,gst_amount,cashflow_entities(name)").eq("company_id", company_id).eq("vendor_id", vendor_id).execute().data or []
                duplicate_rows = [row for row in legacy_rows if (
                    normalized_bill_number and normalize_invoice_number(row.get("bill_number")) == normalized_bill_number
                ) or (
                    not normalized_bill_number and str(row.get("bill_date") or "")[:10] == str(bill_date)[:10] and round(float(row.get("amount") or 0), 2) == round(amount, 2)
                )]
            if duplicate_rows and not force_save:
                existing = duplicate_rows[0]
                return func.HttpResponse(_safe_json({
                    "ok": False,
                    "duplicate": True,
                    "error": "Potential duplicate detected.",
                    "data": {"existing": existing, "kind": "bill"},
                }), mimetype="application/json", status_code=409)

            bill_number = supplied_bill_number or f"BILL-{int(datetime.now().timestamp())}"
            if force_save:
                bill_number = f"{bill_number}-DUP-{int(datetime.now().timestamp())}"
                dedup_fingerprint = f"{dedup_fingerprint}-override-{identity.get('user_id')}-{int(datetime.now().timestamp())}"

            new_bill = {
                "company_id": company_id,
                "vendor_id": vendor_id,
                "bill_number": bill_number,
                "normalized_bill_number": normalized_bill_number,
                "dedup_fingerprint": dedup_fingerprint,
                "dedup_override": force_save,
                "bill_date": bill_date,
                "due_date": due_date,
                "payment_terms_days": payment_terms_days,
                "amount": amount,
                "gst_amount": gst_amount,
                "tds_amount": tds_amount,
                "created_by": identity.get("user_id"),
                "status": "pending"
                ,"line_items": line_items
                ,"party_details": party_details
            }
            
            try:
                response = supabase.table('cashflow_bills').insert(new_bill).execute()
            except Exception as insert_error:
                if "23505" in str(insert_error) or "duplicate key value" in str(insert_error).lower():
                    raced = supabase.table("cashflow_bills").select("id,bill_number,bill_date,amount,gst_amount,cashflow_entities(name)").eq("company_id", company_id).eq("dedup_fingerprint", dedup_fingerprint).limit(1).execute().data or []
                    if raced and not force_save:
                        return func.HttpResponse(_safe_json({"ok": False, "duplicate": True, "error": "Potential duplicate detected.", "data": {"existing": raced[0], "kind": "bill"}}), mimetype="application/json", status_code=409)
                raise
            audit.record(supabase, tenant_context, "upload", "cashflow_bill", response.data[0].get("id") if response.data else None, "success", {"source": "ap", "bill_number": bill_number, "force_save": force_save})
            
            # Re-query with vendor relationship
            bill_with_vendor = (
                supabase.table('cashflow_bills')
                .select('*, cashflow_entities(id, name, gstin)')
                .eq('company_id', company_id)
                .eq('id', response.data[0]['id'])
                .single()
                .execute()
            )
            
            return func.HttpResponse(json.dumps({"ok": True, "data": bill_with_vendor.data}), mimetype="application/json")

        # 4. POST /api/cashflow/ap/approve
        elif req.method == "POST" and action == "approve":
            auth = require_cashflow_tenant(req)
            if not auth["ok"]:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": auth["error"]}),
                    mimetype="application/json",
                    status_code=auth["status_code"],
                )
            identity = auth.get("identity") or {}
            company_id = str(identity.get("company_id") or "").strip()
            if not company_id:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Complete workspace onboarding before approving bills."}),
                    mimetype="application/json",
                    status_code=403,
                )
            if not identity_can_approve(identity):
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Only owners or admins can approve bills."}),
                    mimetype="application/json",
                    status_code=403,
                )
            try:
                data = req.get_json()
            except ValueError:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Request body must be valid JSON"}),
                    mimetype="application/json",
                    status_code=400,
                )

            bill_id = str(data.get("bill_id") or "").strip()
            if not bill_id:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "bill_id is required"}),
                    mimetype="application/json",
                    status_code=400,
                )

            current = (
                supabase.table('cashflow_bills')
                .select('id,status')
                .eq('company_id', company_id)
                .eq('id', bill_id)
                .limit(1)
                .execute()
            )
            current_rows = current.data or []
            if not current_rows:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Bill not found"}),
                    mimetype="application/json",
                    status_code=404,
                )

            current_status = str(current_rows[0].get("status") or "")
            if current_status == "approved":
                approved = (
                    supabase.table('cashflow_bills')
                    .select('*, cashflow_entities(id, name, gstin)')
                    .eq('company_id', company_id)
                    .eq('id', bill_id)
                    .single()
                    .execute()
                )
                return func.HttpResponse(json.dumps({"ok": True, "data": approved.data}), mimetype="application/json")

            if current_status != "pending":
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": f"Only pending bills can be approved. Current status: {current_status}"}),
                    mimetype="application/json",
                    status_code=400,
                )

            updated = (
                supabase.table('cashflow_bills')
                .update({"status": "approved"})
                .eq('company_id', company_id)
                .eq('id', bill_id)
                .execute()
            )

            updated_rows = updated.data or []
            if not updated_rows:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Unable to approve bill"}),
                    mimetype="application/json",
                    status_code=500,
                )

            bill_with_vendor = (
                supabase.table('cashflow_bills')
                .select('*, cashflow_entities(id, name, gstin)')
                .eq('company_id', company_id)
                .eq('id', bill_id)
                .single()
                .execute()
            )
            return func.HttpResponse(json.dumps({"ok": True, "data": bill_with_vendor.data}), mimetype="application/json")

        return func.HttpResponse(
            json.dumps({"ok": False, "error": f"Unsupported AP route action '{action}' for method {req.method}"}),
            mimetype="application/json",
            status_code=404,
        )

    except Exception as e:
        logging.error(f"Error in AP API: {str(e)}")
        return func.HttpResponse(json.dumps({"ok": False, "error": str(e)}), mimetype="application/json", status_code=500)