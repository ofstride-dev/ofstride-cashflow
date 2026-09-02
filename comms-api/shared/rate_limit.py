import os
import threading
import time

_lock = threading.Lock()
_buckets: dict[str, list[float]] = {}


def allow(key: str) -> tuple[bool, int]:
    limit = max(1, int(os.environ.get("EMAIL_RATE_LIMIT_REQUESTS", "10")))
    window = max(1, int(os.environ.get("EMAIL_RATE_LIMIT_WINDOW_SECONDS", "60")))
    now = time.time()
    with _lock:
        recent = [value for value in _buckets.get(key, []) if value >= now - window]
        if len(recent) >= limit:
            retry = max(1, int(window - (now - recent[0])))
            _buckets[key] = recent
            return False, retry
        recent.append(now)
        _buckets[key] = recent
        return True, 0