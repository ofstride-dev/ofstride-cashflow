from datetime import datetime, timezone

from shared.tenant import TenantContext


class MissingTableError(RuntimeError):
    """Raised when the petty-cash table is not available."""


def is_missing_table_error(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    return "pgrst205" in text or "could not find the table" in text


class PettyCashRepository:
    """All petty-cash reads and writes scoped to a verified tenant."""

    def __init__(self, client):
        self._client = client

    def _table(self):
        return self._client.table("cashflow_petty_cash")

    def list_entries(self, context: TenantContext):
        try:
            return self._table().select("*").eq("company_id", context.company_id).order("entry_date", desc=True).execute()
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise

    def create_entry(self, context: TenantContext, payload: dict):
        entry = {**payload, "company_id": context.company_id, "recorded_by": context.user_id, "status": "pending"}
        try:
            return self._table().insert(entry).execute()
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise

    def get_entry(self, context: TenantContext, entry_id: str):
        try:
            return self._table().select("*").eq("company_id", context.company_id).eq("id", entry_id).limit(1).execute()
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise

    def approve_entry(self, context: TenantContext, entry_id: str):
        try:
            return (
                self._table()
                .update({"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat()})
                .eq("company_id", context.company_id)
                .eq("id", entry_id)
                .execute()
            )
        except Exception as exc:
            if is_missing_table_error(exc):
                raise MissingTableError(str(exc)) from exc
            raise