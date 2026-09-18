import azure.functions as func
import json
import logging
from datetime import datetime, timedelta
from shared.db import get_supabase_client
from shared.admin_auth import identity_can_approve, require_cashflow_tenant
from cashflow.ar import ARRepository, MissingTableError
from shared.dedup import document_fingerprint, duplicate_key, normalize_invoice_number
from shared.tenant import audit, TenantContext


def _to_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_item_services(raw_value) -> list[str]:
    if raw_value is None:
        return []

    if isinstance(raw_value, list):
        values = raw_value
    elif isinstance(raw_value, str):
        values = raw_value.split("\n")
    else:
        values = [str(raw_value)]

    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _compose_notes(notes: str, item_services: list[str]) -> str:
    base = str(notes or "").strip()
    if not item_services:
        return base

    items_block = "\n".join([f"- {item}" for item in item_services])
    if base:
        return f"{base}\n\nItems/Services:\n{items_block}"
    return f"Items/Services:\n{items_block}"


def _is_missing_table_error(exc: Exception) -> bool:
    text = str(exc or "")
    lowered = text.lower()
    return "pgrst205" in lowered or "could not find the table" in lowered


def _safe_json(data) -> str:
    """json-serialize payload, falling back to a stable error shape."""
    try:
        return json.dumps(data)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "Response serialization failed"})


def _insert_invoice_with_fallback(supabase, invoice_payload: dict):
    try:
        return supabase.table('cashflow_invoices').insert(invoice_payload).execute()
    except Exception as exc:
        message = str(exc).lower()
        # Backward-compatible fallback for deployments where optional columns are missing.
        if "column" in message and ("does not exist" in message or "not found" in message):
            fallback_payload = dict(invoice_payload)
            if "line_items" in message:
                fallback_payload.pop("line_items", None)
                return _insert_invoice_with_fallback(supabase, fallback_payload)
            if "party_details" in message:
                fallback_payload.pop("party_details", None)
                return _insert_invoice_with_fallback(supabase, fallback_payload)
            if "item_services" in message:
                fallback_payload.pop("item_services", None)
                try:
                    return supabase.table('cashflow_invoices').insert(fallback_payload).execute()
                except Exception as exc2:
                    msg2 = str(exc2).lower()
                    if "column" in msg2 and ("does not exist" in msg2 or "not found" in msg2):
                        fallback_payload.pop("notes", None)
                        return supabase.table('cashflow_invoices').insert(fallback_payload).execute()
                    raise

            if "notes" in message:
                fallback_payload.pop("notes", None)
                try:
                    return supabase.table('cashflow_invoices').insert(fallback_payload).execute()
                except Exception as exc3:
                    msg3 = str(exc3).lower()
                    if "column" in msg3 and ("does not exist" in msg3 or "not found" in msg3):
                        fallback_payload.pop("item_services", None)
                        return supabase.table('cashflow_invoices').insert(fallback_payload).execute()
                    raise

            fallback_payload.pop("item_services", None)
            try:
                return supabase.table('cashflow_invoices').insert(fallback_payload).execute()
            except Exception:
                fallback_payload.pop("notes", None)
                return supabase.table('cashflow_invoices').insert(fallback_payload).execute()
        raise


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing Accounts Receivable request.')
    action = req.route_params.get("action")
    if not action and req.method == "GET":
        action = "list"

    try:
        auth = require_cashflow_tenant(req)
        if not auth["ok"]:
            return func.HttpResponse(
                _safe_json({"ok": False, "error": auth["error"]}),
                mimetype="application/json",
                status_code=auth["status_code"],
            )

        supabase = get_supabase_client()
        identity = auth.get("identity") or {}
        context = auth.get("tenant")
        if context is None:
            return func.HttpResponse(_safe_json({"ok": False, "error": "Cashflow workspace membership is required."}), mimetype="application/json", status_code=403)
        repository = ARRepository(supabase)
        company_id = str(identity.get("company_id") or "").strip()
        if not company_id:
            return func.HttpResponse(
                _safe_json({"ok": False, "error": "Complete workspace onboarding before using Accounts Receivable."}),
                mimetype="application/json",
                status_code=403,
            )
        tenant_context = TenantContext(user_id=str(identity.get("user_id") or ""), company_id=company_id, role=str(identity.get("role") or ""), email=identity.get("email"), full_name=identity.get("full_name"))

        # 1. GET /api/cashflow/ar/list -> Fetch all outbound invoices
        if req.method == "GET" and action == "list":
            try:
                response = repository.list_invoices(context)
            except MissingTableError:
                return func.HttpResponse(_safe_json({"ok": True, "data": []}), mimetype="application/json")
                raise

            return func.HttpResponse(_safe_json({"ok": True, "data": response.data}), mimetype="application/json")

        if req.method == "POST" and action in {"update", "delete", "void"}:
            if not identity_can_approve(identity):
                return func.HttpResponse(_safe_json({"ok": False, "error": "Only owners, admins, or finance users can modify AR records."}), mimetype="application/json", status_code=403)
            data = req.get_json(); invoice_id = str(data.get("invoice_id") or "").strip(); reason = str(data.get("reason") or "").strip(); comment = str(data.get("comment") or "").strip()
            if not invoice_id or not reason or (reason == "Other" and not comment):
                return func.HttpResponse(_safe_json({"ok": False, "error": "invoice_id and a mandatory reason are required."}), mimetype="application/json", status_code=400)
            current = supabase.table("cashflow_invoices").select("*").eq("company_id", company_id).eq("id", invoice_id).limit(1).execute().data or []
            if not current: return func.HttpResponse(_safe_json({"ok": False, "error": "Invoice not found."}), mimetype="application/json", status_code=404)
            record = current[0]
            if action == "delete":
                audit.record(supabase, tenant_context, "delete", "cashflow_invoice", invoice_id, "success", {"reason": reason, "comment": comment, "record": record})
                supabase.table("cashflow_transactions").delete().eq("company_id", company_id).eq("invoice_id", invoice_id).execute()
                supabase.table("cashflow_invoices").delete().eq("company_id", company_id).eq("id", invoice_id).execute()
                return func.HttpResponse(_safe_json({"ok": True, "data": {"id": invoice_id, "deleted": True}}), mimetype="application/json")
            if action == "void":
                updated = supabase.table("cashflow_invoices").update({"status": "cancelled"}).eq("company_id", company_id).eq("id", invoice_id).execute()
                audit.record(supabase, tenant_context, "void", "cashflow_invoice", invoice_id, "success", {"reason": reason, "comment": comment, "record": record})
                return func.HttpResponse(_safe_json({"ok": True, "data": (updated.data or [record])[0]}), mimetype="application/json")
            allowed = {key: data[key] for key in ("invoice_number", "invoice_date", "due_date", "amount", "gst_amount", "discount_percent", "notes", "line_items", "party_details") if key in data}
            if not allowed: return func.HttpResponse(_safe_json({"ok": False, "error": "No editable invoice fields were provided."}), mimetype="application/json", status_code=400)
            updated = supabase.table("cashflow_invoices").update(allowed).eq("company_id", company_id).eq("id", invoice_id).execute()
            audit.record(supabase, tenant_context, "edit", "cashflow_invoice", invoice_id, "success", {"reason": reason, "comment": comment, "changes": allowed})
            return func.HttpResponse(_safe_json({"ok": True, "data": (updated.data or [record])[0]}), mimetype="application/json")

        # 2. POST /api/cashflow/ar/create -> Create a new sales invoice
        elif req.method == "POST" and action == "create":
            try:
                data = req.get_json()
            except ValueError:
                return func.HttpResponse(_safe_json({"ok": False, "error": "Invalid JSON body"}), mimetype="application/json", status_code=400)

            customer_id = repository.get_or_create_customer(context, data.get("customer_name"), data.get("customer_gstin"))
            item_services = _normalize_item_services(data.get("item_services"))
            line_items = data.get("line_items") if isinstance(data.get("line_items"), list) else []
            party_details = data.get("party_details") if isinstance(data.get("party_details"), dict) else {}

            amount = _to_float(data.get("amount"), 0.0)
            discount_percent = max(0.0, min(100.0, _to_float(data.get("discount_percent"), 0.0)))
            taxable_amount = round(amount * (1 - discount_percent / 100), 2)
            gst_rate = max(0.0, min(100.0, _to_float(data.get("gst_rate"), 0.0)))
            gst_amount = round(taxable_amount * gst_rate / 100, 2) if "gst_rate" in data else _to_float(data.get("gst_amount"), 0.0)

            invoice_date = data.get("invoice_date") or datetime.now().strftime("%Y-%m-%d")
            # Default due date to 15 days if not specified
            due_date = data.get("due_date") or (datetime.strptime(invoice_date, "%Y-%m-%d") + timedelta(days=15)).strftime("%Y-%m-%d")

            supplied_invoice_number = str(data.get("invoice_number") or "").strip()
            dedup_fingerprint = document_fingerprint(
                party_id=customer_id,
                party_name=data.get("customer_name"),
                document_date=invoice_date,
                amount=taxable_amount,
                gst_amount=gst_amount,
                line_items=line_items,
            )
            normalized_invoice_number, dedup_fingerprint = duplicate_key(supplied_invoice_number, dedup_fingerprint)
            force_save = bool(data.get("force_save"))
            duplicate_query = supabase.table("cashflow_invoices").select("id,invoice_number,invoice_date,amount,gst_amount,cashflow_entities(name)").eq("company_id", company_id).eq("customer_id", customer_id).limit(1)
            if normalized_invoice_number:
                duplicate_query = duplicate_query.eq("normalized_invoice_number", normalized_invoice_number)
            else:
                duplicate_query = duplicate_query.eq("dedup_fingerprint", dedup_fingerprint)
            try:
                duplicate_rows = duplicate_query.execute().data or []
            except Exception as duplicate_error:
                if "column" not in str(duplicate_error).lower():
                    raise
                legacy_rows = supabase.table("cashflow_invoices").select("id,invoice_number,invoice_date,amount,gst_amount,cashflow_entities(name)").eq("company_id", company_id).eq("customer_id", customer_id).execute().data or []
                duplicate_rows = [row for row in legacy_rows if (
                    normalized_invoice_number and normalize_invoice_number(row.get("invoice_number")) == normalized_invoice_number
                ) or (
                    not normalized_invoice_number and str(row.get("invoice_date") or "")[:10] == str(invoice_date)[:10] and round(float(row.get("amount") or 0), 2) == round(taxable_amount, 2) and round(float(row.get("gst_amount") or 0), 2) == round(gst_amount, 2)
                )]
            if duplicate_rows and not force_save:
                existing = duplicate_rows[0]
                return func.HttpResponse(_safe_json({
                    "ok": False,
                    "duplicate": True,
                    "error": "Potential duplicate detected.",
                    "data": {"existing": existing, "kind": "invoice"},
                }), mimetype="application/json", status_code=409)

            invoice_number = supplied_invoice_number or f"INV-{int(datetime.now().timestamp())}"
            if force_save:
                invoice_number = f"{invoice_number}-DUP-{int(datetime.now().timestamp())}"
                dedup_fingerprint = f"{dedup_fingerprint}-override-{identity.get('user_id')}-{int(datetime.now().timestamp())}"

            new_invoice = {
                "company_id": company_id,
                "customer_id": customer_id,
                "invoice_number": invoice_number,
                "normalized_invoice_number": normalized_invoice_number,
                "dedup_fingerprint": dedup_fingerprint,
                "dedup_override": force_save,
                "invoice_date": invoice_date,
                "due_date": due_date,
                "amount": taxable_amount,
                "gst_amount": gst_amount,
                "status": data.get("status", "pending"),
                "irn_number": data.get("irn_number", None),
                "is_proforma": False,
                "discount_percent": discount_percent,
                "invoice_raised_by": data.get("invoice_raised_by") or None,
                "created_by": identity.get("user_id"),
                "notes": _compose_notes(data.get("notes", ""), item_services),
                "item_services": item_services,
                "line_items": line_items,
                "party_details": party_details,
            }

            try:
                response = _insert_invoice_with_fallback(supabase, new_invoice)
                audit.record(supabase, tenant_context, "upload", "cashflow_invoice", response.data[0].get("id") if response.data else None, "success", {"source": "ar", "invoice_number": invoice_number, "force_save": force_save})
            except Exception as insert_error:
                if _is_missing_table_error(insert_error):
                    return func.HttpResponse(
                        _safe_json({"ok": False, "error": "Cashflow invoices table not configured. Run the cashflow schema migration."}),
                        mimetype="application/json",
                        status_code=500,
                    )
                if "23505" in str(insert_error) or "duplicate key value" in str(insert_error).lower():
                    raced = supabase.table("cashflow_invoices").select("id,invoice_number,invoice_date,amount,gst_amount,cashflow_entities(name)").eq("company_id", company_id).eq("dedup_fingerprint", dedup_fingerprint).limit(1).execute().data or []
                    if raced and not force_save:
                        return func.HttpResponse(_safe_json({"ok": False, "duplicate": True, "error": "Potential duplicate detected.", "data": {"existing": raced[0], "kind": "invoice"}}), mimetype="application/json", status_code=409)
                raise

            # Re-fetch with customer details to return to frontend
            try:
                inv_with_customer = (
                    supabase.table('cashflow_invoices')
                    .select('*, cashflow_entities!cashflow_invoices_customer_id_fkey(id, name, gstin)')
                    .eq('company_id', company_id)
                    .eq('id', response.data[0]['id'])
                    .single()
                    .execute()
                )
            except Exception:
                inv_with_customer = None

            return func.HttpResponse(
                _safe_json({"ok": True, "data": (inv_with_customer.data if inv_with_customer else response.data[0])}),
                mimetype="application/json",
            )

        # 3. POST /api/cashflow/ar/collect -> Record a payment in cashflow_transactions
        elif req.method == "POST" and action == "collect":
            data = req.get_json()
            invoice_id = data.get("invoice_id")
            if not invoice_id:
                return func.HttpResponse(_safe_json({"ok": False, "error": "invoice_id is required"}), mimetype="application/json", status_code=400)

            invoice_res = (
                supabase.table('cashflow_invoices')
                .select('id, amount, gst_amount, status')
                .eq('company_id', company_id)
                .eq('id', invoice_id)
                .limit(1)
                .execute()
            )
            invoice_rows = invoice_res.data or []
            if not invoice_rows:
                return func.HttpResponse(_safe_json({"ok": False, "error": "Invoice not found"}), mimetype="application/json", status_code=404)

            invoice = invoice_rows[0]
            current_status = str(invoice.get("status") or "")
            if current_status.lower() not in {"approved", "overdue"}:
                return func.HttpResponse(_safe_json({"ok": False, "error": "The invoice must be approved before a collection can be recorded."}), mimetype="application/json", status_code=409)
            if current_status == "paid":
                return func.HttpResponse(_safe_json({"ok": False, "error": "Invoice is already paid"}), mimetype="application/json", status_code=400)

            requested_amount = _to_float(data.get("amount"), 0.0)
            if requested_amount <= 0:
                return func.HttpResponse(_safe_json({"ok": False, "error": "A positive payment amount is required"}), mimetype="application/json", status_code=400)
            tx_sum_res = supabase.table('cashflow_transactions').select('amount').eq('company_id', company_id).eq('invoice_id', invoice_id).execute()
            already_collected = sum(_to_float(t.get("amount"), 0.0) for t in (tx_sum_res.data or []))
            invoice_total = round(_to_float(invoice.get("amount"), 0.0) + _to_float(invoice.get("gst_amount"), 0.0), 2)
            if requested_amount > max(invoice_total - already_collected, 0):
                return func.HttpResponse(_safe_json({"ok": False, "error": "Payment amount cannot exceed the remaining balance due"}), mimetype="application/json", status_code=400)

            new_transaction = {
                "company_id": company_id,
                "invoice_id": invoice_id,
                "transaction_date": data.get("transaction_date", datetime.now().strftime("%Y-%m-%d")),
                "amount": requested_amount,
                "transaction_type": "INFLOW",
                "payment_mode": data.get("payment_mode", "bank_transfer"),
                "reference_no": data.get("reference_no", ""),
                "created_by": identity.get("user_id"),
            }

            try:
                response = supabase.table('cashflow_transactions').insert(new_transaction).execute()
            except Exception as collect_error:
                if _is_missing_table_error(collect_error):
                    return func.HttpResponse(
                        _safe_json({"ok": False, "error": "Cashflow transactions table not configured. Run the cashflow schema migration."}),
                        mimetype="application/json",
                        status_code=500,
                    )
                raise

            total_collected = round(sum(_to_float(t.get("amount"), 0.0) for t in (tx_sum_res.data or [])), 2)
            total_collected = round(total_collected + requested_amount, 2)

            updated_invoice = None
            if total_collected >= invoice_total and invoice_total > 0:
                paid_update = (
                    supabase.table('cashflow_invoices')
                    .update({"status": "paid"})
                    .eq('company_id', company_id)
                    .eq('id', invoice_id)
                    .execute()
                )
                updated_rows = paid_update.data or []
                updated_invoice = updated_rows[0] if updated_rows else None

            return func.HttpResponse(
                _safe_json(
                    {
                        "ok": True,
                        "data": {
                            "transaction": response.data[0],
                            "invoice_status": updated_invoice.get("status") if updated_invoice else current_status,
                            "total_collected": total_collected,
                            "invoice_total": invoice_total,
                        },
                    }
                ),
                mimetype="application/json"
            )

        # 4. POST /api/cashflow/ar/approve -> Transition invoice from pending to approved
        elif req.method == "POST" and action == "approve":
            if not identity_can_approve(identity):
                return func.HttpResponse(_safe_json({"ok": False, "error": "Only owners or admins can approve invoices."}), mimetype="application/json", status_code=403)
            try:
                data = req.get_json()
            except ValueError:
                return func.HttpResponse(_safe_json({"ok": False, "error": "Request body must be valid JSON"}), mimetype="application/json", status_code=400)

            invoice_id = str(data.get("invoice_id") or "").strip()
            if not invoice_id:
                return func.HttpResponse(_safe_json({"ok": False, "error": "invoice_id is required"}), mimetype="application/json", status_code=400)

            current = supabase.table('cashflow_invoices').select('id,status').eq('company_id', company_id).eq('id', invoice_id).limit(1).execute()
            current_rows = current.data or []
            if not current_rows:
                return func.HttpResponse(_safe_json({"ok": False, "error": "Invoice not found"}), mimetype="application/json", status_code=404)

            current_status = str(current_rows[0].get("status") or "")
            if current_status == "approved":
                invoice_data = supabase.table('cashflow_invoices').select('*, cashflow_entities!cashflow_invoices_customer_id_fkey(id, name, gstin)').eq('company_id', company_id).eq('id', invoice_id).single().execute()
                return func.HttpResponse(_safe_json({"ok": True, "data": invoice_data.data}), mimetype="application/json")

            if current_status != "pending":
                return func.HttpResponse(_safe_json({"ok": False, "error": f"Only pending invoices can be approved. Current status: {current_status}"}), mimetype="application/json", status_code=400)

            update_res = (
                supabase.table('cashflow_invoices')
                .update({"status": "approved"})
                .eq('company_id', company_id)
                .eq('id', invoice_id)
                .execute()
            )

            updated_rows = update_res.data or []
            if not updated_rows:
                return func.HttpResponse(_safe_json({"ok": False, "error": "Unable to approve invoice"}), mimetype="application/json", status_code=500)

            invoice_data = supabase.table('cashflow_invoices').select('*, cashflow_entities!cashflow_invoices_customer_id_fkey(id, name, gstin)').eq('company_id', company_id).eq('id', invoice_id).single().execute()
            return func.HttpResponse(_safe_json({"ok": True, "data": invoice_data.data}), mimetype="application/json")

        return func.HttpResponse(
            _safe_json({"ok": False, "error": f"Unsupported AR route action '{action}' for method {req.method}"}),
            mimetype="application/json",
            status_code=404,
        )

    except Exception as e:
        logging.error(f"Error in AR API: {str(e)}")
        return func.HttpResponse(
            _safe_json({"ok": False, "error": str(e)}),
            mimetype="application/json",
            status_code=500
        )