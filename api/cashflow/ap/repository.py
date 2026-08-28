from datetime import date, datetime
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
            response = (
                self._client.table("cashflow_bills")
                .select("*, cashflow_entities(id, name, gstin, msme_category)")
                .eq("company_id", context.company_id)
                .order("created_at", desc=True)
                .execute()
            )
            bill_ids = [row.get("id") for row in (response.data or []) if row.get("id")]
            payments = self._client.table("cashflow_transactions").select("bill_id,amount").eq("company_id", context.company_id).in_("bill_id", bill_ids).execute() if bill_ids else None
            paid = {}
            for row in (payments.data if payments else []) or []:
                paid[row.get("bill_id")] = paid.get(row.get("bill_id"), 0) + float(row.get("amount") or 0)
            for row in response.data or []:
                # AP amount is stored as the gross bill value (net + GST).
                gross = float(row.get("amount") or 0)
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