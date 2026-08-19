"""Tenant-scoped Accounts Receivable feature package."""

from .repository import ARRepository, MissingTableError

__all__ = ["ARRepository", "MissingTableError"]