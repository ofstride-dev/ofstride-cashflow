from __future__ import annotations

import csv
import re
from pathlib import Path

from core.settings import DATA_ROOT
from retrieval.qdrant_store import RetrievedDocument


class LocalConsultantDirectory:
    def __init__(self):
        self._rows: list[dict[str, str]] = []
        self._loaded = False

    def _load_if_needed(self) -> None:
        if self._loaded:
            return

        seed_path = DATA_ROOT / "consultants_seed.csv"
        self._loaded = True
        if not seed_path.exists():
            return

        with seed_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self._rows = [
                {k: str(v or "").strip() for k, v in row.items()}
                for row in reader
            ]

    @staticmethod
    def _infer_domain(row: dict[str, str]) -> str:
        role = (row.get("role") or "").lower()
        email = (row.get("email") or "").lower()
        name = (row.get("name") or "").lower()
        combined = " ".join([role, email, name])

        if any(token in combined for token in ["hr", "payroll", "recruit", "hiring", "eor", "workforce"]):
            return "People & Workforce"
        if any(token in combined for token in ["finance", "tax", "gst", "legal", "compliance", "cfo"]):
            return "Finance & Compliance"
        if any(token in combined for token in ["it", "technology", "digital", "ai", "data", "strategy"]):
            return "Technology & Growth"
        return "Business Consulting"

    @classmethod
    def _infer_brief_summary(cls, row: dict[str, str]) -> str:
        domain = cls._infer_domain(row)
        role = row.get("role") or "Consultant"
        location = row.get("location") or "India"

        if domain == "People & Workforce":
            focus = "workforce planning, HR operations, payroll, and hiring support"
        elif domain == "Finance & Compliance":
            focus = "finance controls, compliance readiness, tax, and regulatory coordination"
        elif domain == "Technology & Growth":
            focus = "digital transformation, IT consulting, AI and data initiatives, and growth execution"
        else:
            focus = "business advisory and execution support"

        return f"{role} based in {location}, supporting {focus}."

    @classmethod
    def _score_row(cls, query: str, row: dict[str, str]) -> float:
        lowered_query = query.lower()
        # Filter single-char tokens to avoid false substring matches (e.g. "a" in "bangalore")
        tokens = [t for t in lowered_query.replace(",", " ").split() if len(t) >= 2]
        domain = cls._infer_domain(row)
        summary = cls._infer_brief_summary(row)
        haystack = " ".join(
            [
                row.get("name", ""),
                row.get("location", ""),
                row.get("role", ""),
                row.get("email", ""),
                domain,
                summary,
            ]
        ).lower()

        score = 0.0
        for token in tokens:
            # Use word-boundary match to avoid "is" matching inside "business"
            if re.search(rf"\b{re.escape(token)}\b", haystack):
                score += 1.0

        if row.get("role") and row.get("role", "").lower() in lowered_query:
            score += 1.5
        if row.get("location") and row.get("location", "").lower() in lowered_query:
            score += 1.0
        return score

    def search(self, *, query: str, k: int = 5) -> list[RetrievedDocument]:
        self._load_if_needed()
        if not self._rows:
            return []

        scored: list[tuple[float, dict[str, str]]] = []
        for row in self._rows:
            score = self._score_row(query, row)
            if score > 0:
                scored.append((score, row))

        if not scored:
            # No keyword matches — return empty rather than unrelated rows
            return []

        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[: max(1, k)]

        results: list[RetrievedDocument] = []
        for score, row in top:
            domain = self._infer_domain(row)
            summary = self._infer_brief_summary(row)
            metadata = {
                "source": "consultants_seed.csv",
                "source_type": "consultant_data",
                "consultant_name": row.get("name", "Unknown"),
                "location": row.get("location", ""),
                "role": row.get("role", "") or domain,
                "email": row.get("email", ""),
                "mobile": row.get("mobile", ""),
                "domain": domain,
                "brief_summary": summary,
            }
            results.append(RetrievedDocument(page_content=summary, metadata=metadata, score=score))

        return results


_local_directory = LocalConsultantDirectory()


def get_local_consultant_directory() -> LocalConsultantDirectory:
    return _local_directory
