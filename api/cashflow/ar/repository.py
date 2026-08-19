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
            return (
                self._client.table("cashflow_invoices")
                .select("*, cashflow_entities!cashflow_invoices_customer_id_fkey(id, name, gstin)")
                .eq("company_id", context.company_id)
                .order("created_at", desc=True)
                .execute()
            )
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise

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