"""Tenant-scoped action audit recording for Cashflow.

Recording is strictly scoped by ``TenantContext.company_id`` and is built to
never block business flow: if the audit table has not been migrated, or the
database client is unavailable, the failure is logged and the call returns
without raising. Tenants can therefore never be coupled to audit availability.
"""

import logging

from typing import Any

_logger = logging.getLogger("ofstride.cashflow.audit")

AUDIT_TABLE = "cashflow_audit"


def _scoped_payload(context, action: str, resource_type: str, resource_id: str, result: str, details: dict) -> dict:
    return {
        "company_id": context.company_id,
        "user_id": context.user_id,
        "role": context.role,
        "action": action or "unknown",
        "resource_type": resource_type,
        "resource_id": resource_id,
        "result": result or "success",
        "details": details or {},
    }


def record(client, context, action: str, resource_type: str = None, resource_id: str = None,
           result: str = "success", details: dict | None = None):
    """Insert an audit row scoped to the tenant, never raising on failure.

    ``client`` is a Supabase client. Every written row is forced to carry the
    ``context.company_id`` so audit records are always attributed to the
    verified tenant that performed the action.
    """
    try:
        payload = _scoped_payload(context, action, resource_type, resource_id, result, dict(details or {}))
        return client.table(AUDIT_TABLE).insert(payload).execute()
    except Exception as exc:  # pragma: no cover - defensive guard
        _logger.warning("Audit record skipped (action=%s): %s", action, exc)
        return None