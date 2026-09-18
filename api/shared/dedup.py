"""Fast, deterministic duplicate keys for AP, AR, and imported documents."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def normalize_invoice_number(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def gross_amount(amount: Any, gst_amount: Any = 0) -> float:
    try:
        return round(float(amount or 0) + float(gst_amount or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def document_fingerprint(*, party_id: Any, party_name: Any, document_date: Any, amount: Any, gst_amount: Any = 0, line_items: Any = None, source: str = "manual") -> str:
    payload = {
        "source": str(source or "manual").lower(),
        "party_id": str(party_id or ""),
        "party_name": str(party_name or "").strip().lower(),
        "date": str(document_date or "")[:10],
        "gross": f"{gross_amount(amount, gst_amount):.2f}",
        "line_items": line_items if isinstance(line_items, list) else [],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def duplicate_key(invoice_number: Any, fingerprint: str) -> tuple[str | None, str]:
    normalized = normalize_invoice_number(invoice_number)
    return (normalized or None, fingerprint)
