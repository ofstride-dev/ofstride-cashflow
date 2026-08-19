from datetime import datetime

from shared.tenant import TenantContext


class MissingTableError(RuntimeError):
    """Raised when a payments table is missing from the deployed schema."""


def is_missing_table_error(exc: BaseException) -> bool:
    lowered = str(exc or "").lower()
    return "pgrst205" in lowered or "could not find the table" in lowered


class PaymentsRepository:
    """Tenant-scoped payment transaction access."""

    def __init__(self, client):
        self._client = client

    def list_transactions(self, context: TenantContext):
        try:
            return (
                self._client.table("cashflow_transactions")
                .select("*")
                .eq("company_id", context.company_id)
                .order("transaction_date", desc=True)
                .execute()
            )
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise

    def get_parent(self, context: TenantContext, resource_type: str, resource_id: str):
        table = "cashflow_invoices" if resource_type == "invoice" else "cashflow_bills"
        try:
            return (
                self._client.table(table)
                .select("id, amount, gst_amount, status")
                .eq("company_id", context.company_id)
                .eq("id", resource_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise

    @staticmethod
    def validate_payment(parent, amount: float, transaction_date=None):
        """Validate a payment against the already tenant-scoped parent row."""
        rows = getattr(parent, "data", None) or []
        if not rows:
            return "Payment parent resource not found."
        document = rows[0]
        if str(document.get("status") or "").lower() == "cancelled":
            return "Payments cannot be recorded for a cancelled document."
        try:
            if float(amount) > float(document.get("amount") or 0):
                return "Payment amount cannot exceed the parent document amount."
        except (TypeError, ValueError):
            return "Parent document amount is invalid."
        if transaction_date:
            try:
                datetime.strptime(str(transaction_date)[:10], "%Y-%m-%d")
            except ValueError:
                return "Invalid transaction_date. Use YYYY-MM-DD."
        return None

    def create_transaction(self, context: TenantContext, payload: dict):
        transaction = {
            **payload,
            "company_id": context.company_id,
            "created_by": context.user_id,
            "transaction_date": payload.get("transaction_date") or datetime.now().strftime("%Y-%m-%d"),
        }
        try:
            return self._client.table("cashflow_transactions").insert(transaction).execute()
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise