from datetime import date, datetime
from shared.tenant import TenantContext


class MissingTableError(RuntimeError):
    """Raised when an AR table is missing from the deployed schema."""


def is_missing_table_error(exc: BaseException) -> bool:
    lowered = str(exc or "").lower()
    return "pgrst205" in lowered or "could not find the table" in lowered


class ARRepository:
    """Tenant-scoped invoice and customer data access for Accounts Receivable."""

    def __init__(self, client):
        self._client = client

    def list_invoices(self, context: TenantContext):
        try:
            response = (
                self._client.table("cashflow_invoices")
                .select("*, cashflow_entities!cashflow_invoices_customer_id_fkey(id, name, gstin)")
                .eq("company_id", context.company_id)
                .order("created_at", desc=True)
                .execute()
            )
            invoice_ids = [row.get("id") for row in (response.data or []) if row.get("id")]
            payments = self._client.table("cashflow_transactions").select("invoice_id,amount").eq("company_id", context.company_id).in_("invoice_id", invoice_ids).execute() if invoice_ids else None
            paid = {}
            for row in (payments.data if payments else []) or []:
                paid[row.get("invoice_id")] = paid.get(row.get("invoice_id"), 0) + float(row.get("amount") or 0)
            for row in response.data or []:
                gross = float(row.get("amount") or 0) + float(row.get("gst_amount") or 0)
                row["balance_due"] = round(max(gross - paid.get(row.get("id"), 0), 0), 2)
                row.update(self._aging(row.get("due_date"), row["balance_due"], row.get("status")))
            return response
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise

    @staticmethod
    def _aging(due_date, balance_due, status):
        if str(status or "").lower() == "paid" or balance_due <= 0:
            return {"aging_category": "Paid", "aging_label": "Paid", "days_overdue": 0}
        try:
            due = datetime.strptime(str(due_date)[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return {"aging_category": "Not Due", "aging_label": "Due date unavailable", "days_overdue": 0}
        days = (due - date.today()).days
        if days < 0:
            return {"aging_category": "Overdue", "aging_label": f"Overdue by {abs(days)} days", "days_overdue": abs(days)}
        if days <= 7:
            return {"aging_category": "Due Soon", "aging_label": f"Due in {days} days", "days_overdue": 0}
        return {"aging_category": "Not Due", "aging_label": "Not due", "days_overdue": 0}

    def get_or_create_customer(self, context: TenantContext, customer_name, gstin=None) -> str:
        customer_name = (customer_name or "").strip() or "Walk-in Customer"
        result = (
            self._client.table("cashflow_entities")
            .select("id")
            .eq("company_id", context.company_id)
            .eq("name", customer_name)
            .eq("entity_type", "customer")
            .execute()
        )
        if result.data:
            return result.data[0]["id"]

        created = self._client.table("cashflow_entities").insert({
            "name": customer_name,
            "company_id": context.company_id,
            "entity_type": "customer",
            "gstin": gstin if gstin else None,
            "msme_registered": False,
            "msme_category": "none",
        }).execute()
        return created.data[0]["id"]