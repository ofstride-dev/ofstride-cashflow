"""Authoritative Cashflow role and permission policy decisions."""

from typing import Any

CASHFLOW_ROLES = frozenset({"owner", "admin", "finance", "employee"})
CASHFLOW_APPROVER_ROLES = frozenset({"owner", "admin", "finance"})


def role_of(identity: dict[str, Any] | None) -> str:
    return str((identity or {}).get("role") or "").strip().lower()


def can_use_cashflow(identity: dict[str, Any] | None) -> bool:
    identity = identity or {}
    return bool(str(identity.get("company_id") or "").strip() and role_of(identity) in CASHFLOW_ROLES)


def can_approve_cashflow(identity: dict[str, Any] | None) -> bool:
    return role_of(identity) in CASHFLOW_APPROVER_ROLES


def can_manage_invites(identity: dict[str, Any] | None) -> bool:
    return can_approve_cashflow(identity)


def can_create_payments(identity: dict[str, Any] | None) -> bool:
    return can_approve_cashflow(identity)


def can_view_expense_admin_queue(identity: dict[str, Any] | None) -> bool:
    return can_approve_cashflow(identity)