from shared.tenant import TenantContext


class MissingTableError(RuntimeError):
    """Raised when a Supabase query targets a table that does not exist."""


def is_missing_table_error(exc: BaseException) -> bool:
    lowered = str(exc or "").lower()
    return "pgrst205" in lowered or "could not find the table" in lowered


class APRepository:
    """Tenant-scoped read and related-resource access for Accounts Payable.

    Wraps read and related-resource paths so every query and mutation is scoped
    to the verified ``TenantContext.company_id`` and preserves the adapter's
    response shape.
    """

    def __init__(self, client):
        self._client = client

    def list_bills(self, context: TenantContext):
        """List bills with their vendor, scoped to the tenant company.

        Returns the raw result object (``.data`` holds the rows). Raises
        ``MissingTableError`` for a missing/unmigrated table so callers can
        fall back to an empty payload without leaking database details.
        """
        try:
            return (
                self._client.table("cashflow_bills")
                .select("*, cashflow_entities(id, name, gstin, msme_category)")
                .eq("company_id", context.company_id)
                .order("created_at", desc=True)
                .execute()
            )
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise

    def get_or_create_vendor(self, context: TenantContext, vendor_name, gstin=None):
        """Return an existing vendor id or create one, scoped to the tenant.

        The vendor lookup and any insert are both filtered by
        ``context.company_id`` so a tenant can never resolve or mutate a vendor
        that belongs to another company.
        """
        vendor_name = (vendor_name or "").strip() or "Unassigned Vendor"

        res = (
            self._client.table("cashflow_entities")
            .select("id")
            .eq("company_id", context.company_id)
            .eq("name", vendor_name)
            .eq("entity_type", "vendor")
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]

        new_vendor = {
            "name": vendor_name,
            "company_id": context.company_id,
            "entity_type": "vendor",
            "gstin": gstin if gstin else None,
            "msme_registered": False,
            "msme_category": "none",
        }
        v_res = self._client.table("cashflow_entities").insert(new_vendor).execute()
        return v_res.data[0]["id"]