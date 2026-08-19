import azure.functions as func
import json
import logging
from shared.db import get_supabase_client
from shared.admin_auth import identity_can_approve, require_cashflow_tenant
from cashflow.pettycash import MissingTableError, PettyCashRepository

def ai_categorize_expense(description: str) -> tuple[str, bool]:
    desc_lower = description.lower().strip()
    if any(word in desc_lower for word in ['uber', 'ola', 'taxi', 'train', 'metro', 'flight', 'bus', 'cab', 'fuel', 'petrol', 'diesel', 'parking', 'toll']):
        return "Travel & Transport", True
    elif any(word in desc_lower for word in ['swiggy', 'zomato', 'lunch', 'dinner', 'breakfast', 'tea', 'coffee', 'snacks', 'restaurant', 'food']):
        return "Meals & Entertainment", True
    elif any(word in desc_lower for word in ['paper', 'pen', 'print', 'ink', 'stapler', 'notebook', 'stationery', 'marker']):
        return "Office Supplies", True
    elif any(word in desc_lower for word in ['internet', 'wifi', 'broadband', 'phone', 'mobile', 'recharge', 'sim', 'postpaid']):
        return "Utilities & Telecom", True
    elif any(word in desc_lower for word in ['rent', 'lease', 'coworking', 'office rent', 'workspace']):
        return "Rent & Facilities", True
    elif any(word in desc_lower for word in ['repair', 'maintenance', 'service', 'electrician', 'plumber', 'cleaning']):
        return "Repairs & Maintenance", True
    elif any(word in desc_lower for word in ['software', 'saas', 'subscription', 'license', 'zoom', 'google workspace', 'microsoft 365']):
        return "Software & Subscriptions", True
    elif any(word in desc_lower for word in ['courier', 'shipping', 'delivery', 'post', 'bluedart', 'dtdc']):
        return "Logistics & Courier", True
    elif any(word in desc_lower for word in ['salary', 'wage', 'staff advance', 'employee advance', 'reimbursement']):
        return "Payroll & Staff", True
    elif any(word in desc_lower for word in ['gst', 'tds', 'tax', 'challan', 'government fee', 'compliance fee']):
        return "Taxes & Compliance", True
    elif any(word in desc_lower for word in ['advert', 'marketing', 'facebook ads', 'google ads', 'promotion', 'campaign']):
        return "Marketing & Promotion", True
    elif any(word in desc_lower for word in ['hotel', 'stay', 'accommodation']):
        return "Travel Stay", True
    elif any(word in desc_lower for word in ['medical', 'pharmacy', 'medicine', 'clinic']):
        return "Health & Safety", True
    elif any(word in desc_lower for word in ['bank charge', 'processing fee', 'transaction fee', 'interest', 'emi']):
        return "Banking & Finance Charges", True
    return "Uncategorized", False


def _is_missing_column_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "column" in message and ("does not exist" in message or "not found" in message)


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing Petty Cash request.')
    action = req.route_params.get("action")

    auth = require_cashflow_tenant(req)
    if not auth["ok"]:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": auth["error"]}),
            mimetype="application/json",
            status_code=auth["status_code"],
        )
    
    try:
        supabase = get_supabase_client()
        method = req.method
        identity = auth.get("identity") or {}
        context = auth.get("tenant")
        if context is None:
            return func.HttpResponse(json.dumps({"ok": False, "error": "Cashflow workspace membership is required."}), mimetype="application/json", status_code=403)
        repository = PettyCashRepository(supabase)

        if method == "GET" and (not action or action == "list"):
            try:
                response = repository.list_entries(context)
            except MissingTableError:
                return func.HttpResponse(
                    json.dumps({"ok": True, "data": []}),
                    mimetype="application/json",
                    status_code=200
                )
            return func.HttpResponse(
                json.dumps({"ok": True, "data": response.data}),
                mimetype="application/json",
                status_code=200
            )

        elif method == "POST" and (not action or action == "create"):
            req_body = req.get_json()
            description = req_body.get('description', '')
            category = req_body.get('category')
            auto_categorized = False
            
            if not category:
                category, auto_categorized = ai_categorize_expense(description)

            amount = float(req_body.get('amount', 0))
            entry_type = req_body.get('type', 'OUT') # 'IN' or 'OUT'

            # Schema exact mapping
            new_entry = {
                "entry_date": req_body.get('date'),
                "description": description,
                "category": category,
                "auto_categorized": auto_categorized,
                "cash_in": amount if entry_type == 'IN' else 0.00,
                "cash_out": amount if entry_type == 'OUT' else 0.00,
            }

            try:
                response = repository.create_entry(context, new_entry)
            except Exception as insert_error:
                if _is_missing_column_error(insert_error):
                    return func.HttpResponse(
                        json.dumps({"ok": False, "error": "Petty cash schema is missing required columns. Run the latest cashflow schema migration first."}),
                        mimetype="application/json",
                        status_code=409,
                    )
                else:
                    raise

            return func.HttpResponse(
                json.dumps({"ok": True, "message": "Entry logged", "data": response.data[0]}),
                mimetype="application/json",
                status_code=201
            )

        elif req.method == "POST" and action == "approve":
            if not identity_can_approve(identity):
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Only owners or admins can approve petty cash entries."}),
                    mimetype="application/json",
                    status_code=403,
                )
            try:
                req_body = req.get_json()
            except ValueError:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Request body must be valid JSON"}),
                    mimetype="application/json",
                    status_code=400,
                )

            entry_id = str(req_body.get("entry_id") or "").strip()
            if not entry_id:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "entry_id is required"}),
                    mimetype="application/json",
                    status_code=400,
                )

            current = repository.get_entry(context, entry_id)
            current_rows = current.data or []
            if not current_rows:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Entry not found"}),
                    mimetype="application/json",
                    status_code=404,
                )

            current_entry = current_rows[0]
            current_status = str(current_entry.get("status") or "")

            if not current_status:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Approval status column not available. Run the latest cashflow schema migration first."}),
                    mimetype="application/json",
                    status_code=409,
                )

            if current_status == "approved":
                return func.HttpResponse(
                    json.dumps({"ok": True, "data": current_entry}),
                    mimetype="application/json",
                    status_code=200,
                )

            if current_status != "pending":
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": f"Only pending entries can be approved. Current status: {current_status}"}),
                    mimetype="application/json",
                    status_code=400,
                )

            updated = repository.approve_entry(context, entry_id)

            updated_rows = updated.data or []
            if not updated_rows:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Unable to approve entry"}),
                    mimetype="application/json",
                    status_code=500,
                )

            return func.HttpResponse(
                json.dumps({"ok": True, "data": updated_rows[0]}),
                mimetype="application/json",
                status_code=200,
            )

        return func.HttpResponse(
            json.dumps({"ok": False, "error": f"Unsupported petty cash route action '{action}' for method {method}"}),
            mimetype="application/json",
            status_code=404,
        )

    except Exception as e:
        logging.error(f"Error in Petty Cash API: {str(e)}")
        return func.HttpResponse(
            json.dumps({"ok": False, "error": str(e)}),
            mimetype="application/json",
            status_code=500
        )