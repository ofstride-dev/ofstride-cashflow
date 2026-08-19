from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from core.settings import DATA_ROOT


class ServiceCatalog:
    def __init__(self):
        self._services: list[dict[str, str]] = []
        self._loaded = False

    def _load_if_needed(self) -> None:
        if self._loaded:
            return

        services_path = DATA_ROOT / "services.csv"
        self._loaded = True
        if not services_path.exists():
            return

        with services_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self._services = [
                {k: str(v or "").strip() for k, v in row.items()}
                for row in reader
            ]

    def get_all_services(self) -> list[dict[str, str]]:
        """Get all services organized by domain."""
        self._load_if_needed()
        return self._services

    def get_services_by_domain(self, domain: str) -> list[dict[str, str]]:
        """Get services for a specific domain."""
        self._load_if_needed()
        return [s for s in self._services if s.get("domain", "").lower() == domain.lower()]

    def get_services_text(self) -> str:
        """Get formatted service catalog text for LLM context."""
        self._load_if_needed()
        if not self._services:
            return ""

        lines = ["Ofstride Service Offerings:\n"]
        current_domain = None

        for service in self._services:
            domain = service.get("domain", "")
            if domain != current_domain:
                if current_domain is not None:
                    lines.append("")
                lines.append(f"{domain}:")
                current_domain = domain

            name = service.get("service_name", "")
            description = service.get("description", "")
            expertise = service.get("expertise_areas", "")
            
            lines.append(f"  • {name}: {description}")
            if expertise:
                lines.append(f"    Areas: {expertise}")

        return "\n".join(lines)

    def get_services_summary(self) -> str:
        """Get brief summary for UI display."""
        self._load_if_needed()
        lines = ["Our Services:\n"]
        current_domain = None
        current_services = []

        for service in self._services:
            domain = service.get("domain", "")
            name = service.get("service_name", "")
            
            if domain != current_domain:
                if current_domain is not None and current_services:
                    lines.append(f"{current_domain}:\n{', '.join(current_services)}\n")
                current_domain = domain
                current_services = [name]
            else:
                current_services.append(name)

        if current_domain and current_services:
            lines.append(f"{current_domain}:\n{', '.join(current_services)}")

        return "\n".join(lines)


_service_catalog = ServiceCatalog()


def get_service_catalog() -> ServiceCatalog:
    return _service_catalog
