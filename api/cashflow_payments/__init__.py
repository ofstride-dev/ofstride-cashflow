import azure.functions as func
from shared.admin_auth import identity_can_approve, require_cashflow_tenant
from shared.api_contract import create_response
from shared.tenant import audit
from cashflow.payments import PaymentsRepository, MissingTableError


def _body(req):
    try:
        return req.get_json()
    except (TypeError, ValueError):
        return None


def _amount(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None

def main(req: func.HttpRequest) -> func.HttpResponse:
    action = req.route_params.get("action")
    auth = require_cashflow_tenant(req)
    if not auth["ok"]:
        return create_response(auth["status_code"], False, error=auth["error"])

    context = auth.get("tenant")
    if context is None:
        return create_response(403, False, error="Cashflow workspace membership is required.")

    try:
        client = __import__("shared.db", fromlist=["get_supabase_client"]).get_supabase_client()
        repository = PaymentsRepository(client)
    except Exception:
        return create_response(503, False, error="Cashflow payments are temporarily unavailable.")

    if req.method == "GET" and (not action or action == "list"):
        try:
            result = repository.list_transactions(context)
        except MissingTableError:
            return create_response(200, True, data={"transactions": []})
        return create_response(200, True, data={"transactions": result.data or []})

    if req.method == "POST" and (not action or action == "create"):
        if not identity_can_approve(auth.get("identity") or {}):
            return create_response(403, False, error="Only owners, admins, or finance users can create payments.")
        data = _body(req)
        if not isinstance(data, dict):
            return create_response(400, False, error="Request body must be valid JSON.")
        invoice_id = str(data.get("invoice_id") or "").strip()
        bill_id = str(data.get("bill_id") or "").strip()
        if bool(invoice_id) == bool(bill_id):
            return create_response(400, False, error="Exactly one of invoice_id or bill_id is required.")
        amount = _amount(data.get("amount"))
        if amount is None:
            return create_response(400, False, error="A positive payment amount is required.")
        resource_type = "invoice" if invoice_id else "bill"
        resource_id = invoice_id or bill_id
        try:
            parent = repository.get_parent(context, resource_type, resource_id)
        except MissingTableError:
            return create_response(500, False, error="Cashflow payment tables are not configured.")
        if not parent.data:
            return create_response(404, False, error="Payment parent resource not found.")
        validation_error = repository.validate_payment(parent, amount, data.get("transaction_date"))
        if validation_error:
            return create_response(400, False, error=validation_error)
        payload = {
            "invoice_id": invoice_id or None,
            "bill_id": bill_id or None,
            "transaction_date": data.get("transaction_date"),
            "amount": amount,
            "payment_mode": data.get("payment_mode") or "bank_transfer",
            "reference_no": data.get("reference_no") or "",
        }
        try:
            result = repository.create_transaction(context, payload)
        except MissingTableError:
            return create_response(500, False, error="Cashflow payment tables are not configured.")
        audit.record(
            client,
            context,
            action="cashflow.payments.create",
            resource_type=resource_type,
            resource_id=resource_id,
            details={"amount": amount, "transaction_id": (result.data or [{}])[0].get("id")},
        )
        return create_response(201, True, data={"transaction": (result.data or [None])[0]})

    return create_response(
        404,
        False,
        error=f"Unsupported payments route action '{action}' for method {req.method}",
    )