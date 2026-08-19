"""Admin authentication for Azure Functions careers endpoints.

Phase 1: Supabase Auth integration with multi-role support.
- Supports Supabase JWT verification via SUPABASE_URL and SUPABASE_JWT_SECRET.
- Returns role-based context: admin, employer, or jobseeker.
- Falls back to x-admin-key for local dev (Phase 0 compatibility).

Expected shape of the returned auth context::

    {
        "user_id": str,       # matches the JWT 'sub' claim
        "user_name": str,     # email or display name
        "role": str,          # "admin" | "employer" | "jobseeker"
        "company_id": str | None,  # UUID if role is employer
    }
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import azure.functions as func

# Force pipeline trigger — lazy imports fix deployed
_logger = logging.getLogger("ofstride.admin_auth")


class AdminAuthError(Exception):
    """Raised when an admin request fails authentication or authorization."""


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


def _is_local_key_allowed() -> bool:
    """Local key fallback is only safe in dev/test or when explicitly enabled."""
    env = (_env("ENV") or "").lower()
    if env in {"dev", "development", "local", "test"}:
        return True
    return _env("ADMIN_DEV_AUTH_FALLBACK", "false").lower() in {"1", "true", "yes", "on"}


def _get_allowed_admin_roles() -> set[str]:
    raw = _env("ADMIN_ALLOWED_ROLES", "admin")
    return {role.strip().lower() for role in raw.split(",") if role.strip()}


def _get_allowed_admin_emails() -> set[str]:
    raw = _env("ADMIN_ALLOWED_EMAILS", "")
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


# ---------------------------------------------------------------------------
# Request extraction
# ---------------------------------------------------------------------------


def _extract_bearer_token(req: func.HttpRequest) -> str | None:
    auth_header = req.headers.get("Authorization") or req.headers.get("authorization")
    if not auth_header:
        return None
    parts = auth_header.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def _extract_admin_key(req: func.HttpRequest) -> str | None:
    return (
        req.headers.get("x-admin-key")
        or req.headers.get("X-Admin-Key")
        or req.headers.get("X-ADMIN-KEY")
    )

# ---------------------------------------------------------------------------
# Supabase JWT verification
# ---------------------------------------------------------------------------


def _verify_supabase_jwt(token: str) -> dict[str, Any]:
    """Verify a Supabase Auth access token and determine the user's role."""
    supabase_url = _env("SUPABASE_URL")
    if not supabase_url:
        raise AdminAuthError("Supabase authentication is not configured.")

    issuer = supabase_url.rstrip("/") + "/auth/v1"
    audience = _env("SUPABASE_AUTH_AUDIENCE", "authenticated")
    jwt_secret = _env("SUPABASE_JWT_SECRET")

    # Always validate directly against Supabase's Auth API first. This is the
    # most reliable path (it checks the live session, revocation, expiry) and
    # does not depend on a correctly configured legacy JWT secret, which is
    # easy to misconfigure across environments.
    payload = _verify_via_supabase_auth_api(token, supabase_url)

    if payload is None and jwt_secret:
        # Lazy import: PyJWT may not be installed in all environments
        try:
            import jwt
        except ImportError as exc:
            raise AdminAuthError("JWT verification library (pyjwt) is not installed.") from exc

        try:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                audience=audience,
                issuer=issuer,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AdminAuthError("Token has expired.") from exc
        except jwt.InvalidTokenError:
            payload = None

    if payload is None:
        raise AdminAuthError("Invalid authentication token.")

    # ------------------------------------------------------------------
    # Extract user identity
    # ------------------------------------------------------------------
    app_metadata = payload.get("app_metadata") or {}
    user_metadata = payload.get("user_metadata") or {}
    email = (
        payload.get("email")
        or user_metadata.get("email")
        or payload.get("preferred_username")
        or ""
    ).strip()

    user_id = str(payload.get("sub") or payload.get("user_id") or "unknown")
    user_name = (
        user_metadata.get("name")
        or user_metadata.get("full_name")
        or email
        or payload.get("preferred_username")
        or user_id
    )

    # ------------------------------------------------------------------
    # Determine role from JWT claims
    # ------------------------------------------------------------------
    roles: set[str] = set()
    if isinstance(payload.get("role"), str):
        roles.add(payload["role"].lower())
    if isinstance(app_metadata.get("role"), str):
        roles.add(app_metadata["role"].lower())
    if isinstance(app_metadata.get("roles"), list):
        roles.update(str(r).lower() for r in app_metadata["roles"] if r)
    if isinstance(user_metadata.get("role"), str):
        roles.add(user_metadata["role"].lower())

    # Determine primary role (priority: admin > employer > jobseeker)
    primary_role = "jobseeker"
    if "admin" in roles:
        primary_role = "admin"
    elif "employer" in roles:
        primary_role = "employer"

    # Extract company_id for employers
    company_id = (
        app_metadata.get("company_id")
        or user_metadata.get("company_id")
        or None
    )

    # ------------------------------------------------------------------
    # Authorize: require explicit role or allow-listed email for admin
    # ------------------------------------------------------------------
    allowed_roles = _get_allowed_admin_roles()
    allowed_emails = _get_allowed_admin_emails()

    if primary_role == "admin":
        is_admin_by_role = bool(roles & allowed_roles)
        is_admin_by_email = bool(email) and email.lower() in allowed_emails
        if not is_admin_by_role and not is_admin_by_email:
            raise AdminAuthError("Admin privileges required.")

    return {
        "user_id": user_id,
        "user_name": str(user_name),
        "user_email": email.lower() if isinstance(email, str) and email else None,
        "role": primary_role,
        "company_id": str(company_id) if company_id else None,
    }


def _verify_via_supabase_auth_api(token: str, supabase_url: str) -> dict[str, Any] | None:
    """Validate access token using Supabase Auth API and map response to JWT-like claims."""
    key_candidates = [
        _env("SUPABASE_SERVICE_ROLE_KEY"),
        _env("SUPABASE_SERVICE_KEY"),
        _env("SUPABASE_ANON_KEY"),
    ]
    api_keys: list[str] = []
    seen: set[str] = set()
    for key in key_candidates:
        normalized = (key or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            api_keys.append(normalized)

    if not api_keys:
        _logger.error(
            "Supabase auth API check skipped: no SUPABASE_SERVICE_ROLE_KEY, SUPABASE_SERVICE_KEY, or SUPABASE_ANON_KEY configured."
        )
        return None

    user_url = supabase_url.rstrip("/") + "/auth/v1/user"
    user_obj: dict[str, Any] | None = None

    for idx, api_key in enumerate(api_keys):
        req = urlrequest.Request(
            user_url,
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": api_key,
            },
            method="GET",
        )
        try:
            with urlrequest.urlopen(req, timeout=15) as response:
                if response.status != 200:
                    _logger.warning("Supabase auth API rejected token with status %s", response.status)
                    continue
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    user_obj = parsed
                    break
        except urlerror.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            _logger.warning(
                "Supabase auth API rejected token: HTTP %s %s (key_index=%s)%s",
                exc.code,
                exc.reason,
                idx,
                f" body={body[:200]}" if body else "",
            )
            continue
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError) as exc:
            _logger.error("Supabase auth API check failed: %s", exc)
            continue

    if user_obj is None:
        return None

    if not isinstance(user_obj, dict):
        return None

    app_metadata = user_obj.get("app_metadata") or {}
    role = user_obj.get("role") or app_metadata.get("role") or "authenticated"

    return {
        "sub": user_obj.get("id"),
        "email": user_obj.get("email"),
        "role": role,
        "user_metadata": user_obj.get("user_metadata") or {},
        "app_metadata": app_metadata,
    }


# ---------------------------------------------------------------------------
# Local development fallback (server-side key, never in production)
# ---------------------------------------------------------------------------


def _verify_local_admin_key(req: func.HttpRequest) -> dict[str, Any] | None:
    admin_key = _env("ADMIN_API_KEY")
    if not admin_key:
        return None

    provided = _extract_admin_key(req)
    if not provided:
        return None

    if hmac.compare_digest(provided.strip(), admin_key.strip()):
        return {
            "user_id": "admin-local",
            "user_name": "Local Admin",
            "user_email": None,
            "role": "admin",
            "company_id": None,
        }

    return None


# ---------------------------------------------------------------------------
# Public contract
# ---------------------------------------------------------------------------


def require_admin(req: func.HttpRequest) -> dict[str, Any]:
    """Authenticate a request and return auth context.

    Order of checks:
      1. Supabase Authorization: Bearer <jwt> token.
      2. Dev-only x-admin-key header compared with server-side ADMIN_API_KEY.
    """
    # 1. Quick bypass for validation
    bypass = _env("ADMIN_AUTH_DISABLED", "false")
    if bypass.lower() in {"1", "true", "yes", "on"}:
        _logger.warning("Admin auth bypass enabled (ADMIN_AUTH_DISABLED=true). Do not use in production.")
        return {
            "user_id": "admin-bypass",
            "user_name": "Admin (No Auth)",
            "user_email": None,
            "role": "admin",
            "company_id": None,
        }

    # 2. Supabase JWT
    token = _extract_bearer_token(req)
    if token:
        return _verify_supabase_jwt(token)

    # 3. Local key fallback (dev/test only)
    if _is_local_key_allowed():
        fallback = _verify_local_admin_key(req)
        if fallback:
            _logger.warning(
                "Admin request authenticated via local key fallback (user=%s). "
                "This is intended for development only.",
                fallback["user_id"],
            )
            return fallback

    raise AdminAuthError("Authentication required.")


def require_role(req: func.HttpRequest, allowed_roles: list[str]) -> dict[str, Any]:
    """Authenticate and verify the user has one of the allowed roles."""
    auth = require_admin(req)
    if auth["role"] not in allowed_roles:
        raise AdminAuthError(
            f"Access denied. Required role(s): {', '.join(allowed_roles)}. "
            f"Your role: {auth['role']}"
        )
    return auth


def require_authenticated_user(req: func.HttpRequest) -> dict[str, Any]:
    """Require a Supabase bearer token and return auth context.

    This helper is strict and does not allow local key fallback.
    """
    token = _extract_bearer_token(req)
    if not token:
        raise AdminAuthError("Authentication required.")
    return _verify_supabase_jwt(token)