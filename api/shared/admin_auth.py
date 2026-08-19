import os
import logging
import uuid
from typing import Any

import azure.functions as func

from shared.tenant import TenantContext, audit
from shared.tenant.membership import context_from_identity
from shared.tenant.policy import (
    CASHFLOW_APPROVER_ROLES,
    CASHFLOW_ROLES,
    can_approve_cashflow,
    can_use_cashflow,
)


ALLOWED_ROLES = set(CASHFLOW_ROLES) | {"employer"}
APPROVER_ROLES = set(CASHFLOW_APPROVER_ROLES)
WORKSPACE_MEMBER_ROLES = set(CASHFLOW_ROLES)
_logger = logging.getLogger("ofstride.cashflow.auth")


class ProfileLookupError(RuntimeError):
    """Raised when the authenticated user's profile cannot be verified."""

    code = "profile_lookup_failed"


def _get_header(req: func.HttpRequest, name: str) -> str | None:
    """Fetch a header value in a truly case-insensitive way.

    Azure Functions' Python adapter may normalize header casing (often to
    Title-Case like `X-User-Id`). Some clients (curl, browsers, fetch) may send
    different casing. Python dict `.get()` is case-sensitive, so we must scan
    the incoming header keys.
    """

    if not req.headers:
        return None

    target = (name or "").strip().lower()
    if not target:
        return None

    # Fast path for environments where headers are already normalized.
    direct = req.headers.get(name)
    if direct is not None:
        return str(direct).strip() or None

    for key, value in req.headers.items():
        if str(key).strip().lower() == target:
            return str(value).strip() or None

    return None


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    stripped = value.strip()
    return stripped or default


def _allow_local_header_fallback() -> bool:
    env = (_env("ENV") or "").lower()
    if env in {"dev", "development", "local", "test"}:
        return True
    return (_env("ADMIN_DEV_AUTH_FALLBACK", "false") or "false").lower() in {"1", "true", "yes", "on"}


def _profile_to_identity(user_id: str, auth_context: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    profile_found = profile is not None
    profile = profile or {}
    role = str(profile.get("role") or auth_context.get("role") or "employee").strip().lower()
    if role not in ALLOWED_ROLES:
        role = "employee"

    # Cashflow membership is authoritative in the database profile. JWT
    # metadata can be stale after onboarding, transfer, or invite acceptance.
    company_id = profile.get("company_id") or None
    tenant_status = "resolved" if profile_found and company_id else "missing_company" if profile_found else "missing_profile"
    if company_id is not None:
        company_id = str(company_id).strip() or None
        if not _is_valid_uuid(company_id):
            company_id = None
            tenant_status = "invalid_membership"

    return {
        "user_id": user_id,
        "role": role,
        "company_id": company_id,
        "tenant_status": tenant_status,
        "email": auth_context.get("user_email") or profile.get("email"),
        "full_name": profile.get("full_name") or auth_context.get("user_name") or auth_context.get("user_email") or user_id,
        "profile": profile,
    }


def _get_profile_for_user(user_id: str) -> dict[str, Any] | None:
    if not user_id or not _is_valid_uuid(user_id):
        return None

    try:
        from shared.db import get_supabase_client

        supabase = get_supabase_client()
        response = (
            supabase.table("profiles")
            .select("id, full_name, role, company_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None
    except Exception as exc:
        _logger.exception("Cashflow profile lookup failed", extra={"user_id": user_id})
        raise ProfileLookupError("Cashflow profile lookup failed") from exc


def _authenticate_bearer(req: func.HttpRequest) -> dict[str, Any] | None:
    from shared.security.admin_auth import require_authenticated_user

    auth = require_authenticated_user(req)

    user_id = str(auth.get("user_id") or "").strip()
    if not _is_valid_uuid(user_id):
        return None

    profile = _get_profile_for_user(user_id)
    return _profile_to_identity(user_id, auth, profile)


def identity_can_approve(identity: dict[str, Any] | None) -> bool:
    return can_approve_cashflow(identity)


def identity_can_use_cashflow(identity: dict[str, Any] | None) -> bool:
    """Return whether an identity may use company-scoped Cashflow operations.

    Cashflow data access is granted to every member of the workspace,
    including employees who joined through a company invitation. Approval is
    intentionally stricter and remains governed by ``identity_can_approve``.
    """
    return can_use_cashflow(identity)


def _record_tenant_event(context: TenantContext, action: str, resource_type: str = None,
                         resource_id: str = None, result: str = "success", details: dict | None = None):
    """Best-effort audit logging. Never raises and never blocks the request.

    If Supabase is not configured or the audit table is not yet migrated, the
    record is skipped and logged by ``tenant.audit.record``.
    """
    try:
        from shared.db import get_supabase_client
        audit.record(get_supabase_client(), context, action, resource_type, resource_id, result, details)
    except Exception:
        return


def require_cashflow_tenant(req: func.HttpRequest) -> dict[str, Any]:
    """Authenticate a request and require an authenticated workspace tenant.

    Callers must use the returned ``company_id`` for every Cashflow query. The
    value is resolved from the bearer identity/profile (or the explicitly
    opt-in local development auth path), never from request JSON.
    """
    auth = validate_identity_headers(req)
    if not auth.get("ok"):
        return auth

    identity = auth.get("identity") or {}
    company_id = str(identity.get("company_id") or "").strip()
    if not company_id or not identity_can_use_cashflow(identity):
        tenant_status = identity.get("tenant_status") or "missing_company"
        messages = {
            "missing_profile": "Complete your Cashflow profile before using Cashflow.",
            "missing_company": "Complete workspace onboarding before using Cashflow.",
            "invalid_membership": "Your Cashflow workspace membership could not be verified.",
        }
        return {
            "ok": False,
            "status_code": 403,
            "error": messages.get(tenant_status, "Cashflow workspace membership is required."),
            "error_code": tenant_status,
        }

    tenant = context_from_identity(identity)
    _record_tenant_event(tenant, "cashflow.authenticated", result="success")
    return {
        **auth,
        "identity": identity,
        "company_id": company_id,
        "tenant": tenant,
    }


def validate_identity_headers(req: func.HttpRequest) -> dict[str, Any]:
    authorization = _get_header(req, "Authorization")
    if authorization:
        try:
            bearer_identity = _authenticate_bearer(req)
        except ProfileLookupError:
            return {
                "ok": False,
                "status_code": 503,
                "error": "Cashflow identity could not be verified. Please try again.",
                "error_code": ProfileLookupError.code,
            }
        except Exception:
            # A supplied bearer token is authoritative. Never downgrade an
            # invalid/expired token to forgeable local identity headers.
            return {
                "ok": False,
                "status_code": 401,
                "error": "Authentication required.",
            }

        if not bearer_identity:
            return {
                "ok": False,
                "status_code": 401,
                "error": "Authentication required.",
            }

        return {
            "ok": True,
            "status_code": 200,
            "error": None,
            "identity": bearer_identity,
        }

    try:
        bearer_identity = _authenticate_bearer(req)
        if bearer_identity:
            return {
                "ok": True,
                "status_code": 200,
                "error": None,
                "identity": bearer_identity,
            }
    except ProfileLookupError:
        _logger.warning("Cashflow profile lookup failed while resolving request without bearer header")
    except Exception:
        # No bearer header was supplied; local fallback remains controlled by
        # explicit development/test configuration below.
        pass

    user_id = _get_header(req, "x-user-id") or _get_header(req, "x-cashflow-user-id")
    # Some environments normalize hyphenated headers by removing hyphens
    # (e.g. x-user-id -> xuserid). Accept those variants too.
    if not user_id:
        user_id = _get_header(req, "xuserid") or _get_header(req, "xcashflowuserid")
    role_raw = _get_header(req, "x-app-role")
    if not role_raw:
        role_raw = _get_header(req, "xapprole")
    company_id = _get_header(req, "x-company-id")
    if not company_id:
        company_id = _get_header(req, "xcompanyid")
    role = (role_raw or "").strip().lower()

    if not _allow_local_header_fallback():
        return {
            "ok": False,
            "status_code": 401,
            "error": "Authentication required.",
        }

    if not user_id:
        return {
            "ok": False,
            "status_code": 401,
            "error": "Missing required header: x-user-id",
        }

    if not _is_valid_uuid(user_id):
        return {
            "ok": False,
            "status_code": 401,
            "error": "Invalid x-user-id format. Expected UUID.",
        }

    if not role:
        role = "employee"

    if role not in ALLOWED_ROLES:
        return {
            "ok": False,
            "status_code": 403,
            "error": "Unauthorized role for cashflow access",
        }

    return {
        "ok": True,
        "status_code": 200,
        "error": None,
        "identity": {
            "user_id": user_id,
            "role": role,
            "company_id": company_id if _is_valid_uuid(company_id or "") else None,
            "email": None,
            "full_name": "Local Dev User",
            "profile": None,
        },
    }


def validate_admin_or_finance(req: func.HttpRequest) -> bool:
    auth = validate_identity_headers(req)
    return bool(auth.get("ok") and identity_can_approve((auth.get("identity") or {})))


def resolve_identity_headers(req: func.HttpRequest, allow_anonymous: bool = False) -> dict[str, Any]:
    """Resolve cashflow identity, optionally allowing parse-only anonymous requests."""
    auth = validate_identity_headers(req)
    if auth.get("ok"):
        return auth

    if allow_anonymous:
        return {
            "ok": True,
            "status_code": 200,
            "error": None,
            "identity": None,
        }

    return auth