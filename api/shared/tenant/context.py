from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Verified request membership used by tenant-scoped Cashflow code.

    Feature code should depend on this interface rather than the current
    ``profiles.company_id`` storage detail. A future memberships resolver can
    produce the same context without changing feature services or repositories.
    """

    user_id: str
    company_id: str
    role: str
    email: str | None = None
    full_name: str | None = None

    def __post_init__(self) -> None:
        if not self.user_id or not self.company_id or not self.role:
            raise ValueError("TenantContext requires user_id, company_id, and role")