"""
Lightweight in-memory quality counters for the Ofstride chat pipeline.

Tracks per-session-turn outcomes so the /api/health endpoint can surface
aggregate quality signals without requiring an external metrics store.

Counters reset when the function host restarts; they are intentionally
not persisted — they represent recent rolling behaviour, not historical logs.
"""
from __future__ import annotations

import threading
from typing import Any


class QualityCounters:
    """Thread-safe counter set for chat pipeline quality metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total: int = 0
        self._hits: int = 0          # docs retrieved > 0
        self._no_results: int = 0    # docs retrieved == 0 (kb_no_results)
        self._fallbacks: int = 0     # route_decision == "fallback"
        self._templates: int = 0     # route_decision == "deterministic_template"
        self._handoffs: int = 0      # route_decision == "human_handoff"
        self._blocked: int = 0       # route_decision == "blocked"

    def record(self, route_decision: str, doc_count: int) -> None:
        with self._lock:
            self._total += 1
            if route_decision == "fallback":
                self._fallbacks += 1
            elif route_decision == "blocked":
                self._blocked += 1
            elif route_decision == "deterministic_template":
                self._templates += 1
            elif route_decision == "human_handoff":
                self._handoffs += 1
            elif route_decision == "kb_no_results":
                self._no_results += 1
            elif doc_count > 0:
                self._hits += 1
            else:
                self._no_results += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = max(self._total, 1)  # prevent div-zero
            return {
                "total_turns": self._total,
                "hit_rate": round(self._hits / total, 3),
                "no_result_rate": round(self._no_results / total, 3),
                "fallback_rate": round(self._fallbacks / total, 3),
                "template_rate": round(self._templates / total, 3),
                "handoff_count": self._handoffs,
                "blocked_count": self._blocked,
            }


_counters = QualityCounters()


def get_quality_counters() -> QualityCounters:
    return _counters
