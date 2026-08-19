from datetime import date

from shared.tenant import TenantContext


class DashboardRepository:
    """Read-only dashboard data access scoped by a verified tenant context."""

    def __init__(self, client):
        self._client = client

    def _query(self, table_name, select, context: TenantContext, order_by=None, **filters):
        query = self._client.table(table_name).select(select).eq("company_id", context.company_id)
        for key, value in filters.items():
            if key.endswith("_end"):
                key = key[:-4]
            if isinstance(value, tuple) and value[0] == "in":
                query = query.in_(key, value[1])
            elif isinstance(value, tuple) and value[0] == "gte":
                query = query.gte(key, value[1])
            elif isinstance(value, tuple) and value[0] == "lte":
                query = query.lte(key, value[1])
            else:
                query = query.eq(key, value)
        if order_by:
            query = query.order(order_by, desc=False)
        return query.execute()

    def read_window(self, context: TenantContext, start_date: date, end_date: date):
        start_key, end_key = start_date.isoformat(), end_date.isoformat()
        return {
            "transactions": self._query(
                "cashflow_transactions", "amount,invoice_id,bill_id", context,
                transaction_date=("gte", start_key), transaction_date_end=("lte", end_key),
            ),
            "petty_cash": self._query(
                "cashflow_petty_cash", "cash_in,cash_out", context,
                entry_date=("gte", start_key), entry_date_end=("lte", end_key),
            ),
            "pending_invoices": self._query(
                "cashflow_invoices", "amount,gst_amount", context, status="pending",
                is_proforma=False, invoice_date=("gte", start_key), invoice_date_end=("lte", end_key),
            ),
            "payable_bills": self._query(
                "cashflow_bills", "amount,gst_amount", context,
                status=("in", ["pending", "approved"]), bill_date=("gte", start_key), bill_date_end=("lte", end_key),
            ),
            "msme_candidates": self._query(
                "cashflow_bills", "due_date,amount,gst_amount,cashflow_entities!cashflow_bills_vendor_id_fkey(name,msme_category)", context,
                status=("in", ["pending", "approved"]), due_date=("gte", start_key), due_date_end=("lte", end_key),
                order_by="due_date",
            ),
        }

    def read_trend(self, context: TenantContext, start_date: date, end_date: date):
        start_key, end_key = start_date.isoformat(), end_date.isoformat()
        return {
            "transactions": self._query(
                "cashflow_transactions", "transaction_date,amount,invoice_id,bill_id", context,
                transaction_date=("gte", start_key), transaction_date_end=("lte", end_key),
            ),
            "petty_cash": self._query(
                "cashflow_petty_cash", "entry_date,cash_in,cash_out", context,
                entry_date=("gte", start_key), entry_date_end=("lte", end_key),
            ),
        }