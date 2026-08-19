from __future__ import annotations

import threading
import time

from core.settings import get_settings


class InMemoryRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[str, list[float]] = {}

    def check(self, *, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        if limit <= 0 or window_seconds <= 0:
            return True, 0

        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            recent = [ts for ts in self._buckets.get(key, []) if ts >= cutoff]
            if len(recent) >= limit:
                retry_after = int(max(1, window_seconds - (now - recent[0])))
                self._buckets[key] = recent
                return False, retry_after

            recent.append(now)
            self._buckets[key] = recent
            return True, 0


_rate_limiter = InMemoryRateLimiter()


def get_client_key(forwarded_for: str | None, trace_id: str) -> str:
    if not forwarded_for:
        return f"anon:{trace_id[:8]}"

    first = forwarded_for.split(",")[0].strip()
    return first or f"anon:{trace_id[:8]}"


def enforce_rate_limit(*, route_name: str, client_key: str) -> tuple[bool, int]:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return True, 0

    key = f"{route_name}:{client_key}"
    return _rate_limiter.check(
        key=key,
        limit=settings.rate_limit_requests_per_window,
        window_seconds=settings.rate_limit_window_seconds,
    )
