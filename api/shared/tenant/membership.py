from typing import Any

from .context import TenantContext


def context_from_identity(identity: dict[str, Any]) -> TenantContext:
    """Convert a verified membership result into the stable tenant interface."""
    return TenantContext(
        user_id=str(identity.get("user_id") or "").strip(),
        company_id=str(identity.get("company_id") or "").strip(),
        role=str(identity.get("role") or "").strip().lower(),
        email=identity.get("email"),
        full_name=identity.get("full_name"),
    )