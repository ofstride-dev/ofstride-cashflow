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
                "cashflow_transactions", "amount,invoice_id,bill_id,transaction_type", context,
                transaction_date=("gte", start_key), transaction_date_end=("lte", end_key),
            ),
            "expenses": self._query(
                "expenses", "id,amount,spend_date,category,description,status,user_id", context,
                spend_date=("gte", start_key), spend_date_end=("lte", end_key),
            ),
            "pending_invoices": self._query(
                "cashflow_invoices",
                "id,amount,gst_amount,status,is_proforma,due_date,invoice_date", context, status=("in", ["pending", "approved", "overdue"]), is_proforma=False,
            ),
            "payable_bills": self._query(
                "cashflow_bills",
                "id,amount,gst_amount,status,due_date,bill_date", context,
                status=("in", ["pending", "approved", "overdue"]),
            ),
            "accrued_invoices": self._query("cashflow_invoices", "amount,gst_amount,invoice_date,is_proforma", context, invoice_date=("gte", start_key), invoice_date_end=("lte", end_key), is_proforma=False),
            "accrued_bills": self._query("cashflow_bills", "amount,gst_amount,bill_date", context, bill_date=("gte", start_key), bill_date_end=("lte", end_key)),
            "all_transactions": self._query("cashflow_transactions", "amount,invoice_id,bill_id,transaction_type", context),
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
                "cashflow_transactions",
                "transaction_date,amount,invoice_id,bill_id,transaction_type", context,
                transaction_date=("gte", start_key), transaction_date_end=("lte", end_key),
            ),
            "expenses": self._query(
                "expenses", "id,amount,spend_date,category,description,status,user_id", context,
                spend_date=("gte", start_key), spend_date_end=("lte", end_key),
            ),
        }