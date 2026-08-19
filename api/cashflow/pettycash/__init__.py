"""Tenant-scoped petty-cash feature package."""

from .repository import MissingTableError, PettyCashRepository

__all__ = ["MissingTableError", "PettyCashRepository"]