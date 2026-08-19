"""Tenant-scoped payments feature package."""

from .repository import PaymentsRepository, MissingTableError

__all__ = ["PaymentsRepository", "MissingTableError"]