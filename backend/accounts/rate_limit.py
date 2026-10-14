"""
A small in-process sliding-window rate limiter for sign-in and sign-up.

In memory, like the rest of Fork's per-process state, which matches the
single-worker deployment. With more than one worker each would keep its own
counts and the effective limit would multiply -- written down in QUICKSTART
alongside the existing single-worker requirement.
"""

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()
        return hits

    def retry_after(self, key: str) -> int | None:
        """Seconds until `key` may try again, or None if it may now."""
        now = time.monotonic()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) < self.limit:
                return None
            return max(1, int(self.window - (now - hits[0])) + 1)

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(key, now).append(now)
            # Keep the table from growing without bound under a scan.
            if len(self._hits) > 10_000:
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


#: Every login attempt from one client address.
login_by_ip = RateLimiter(limit=20, window_seconds=15 * 60)
#: Failed logins against one account, wherever they come from.
failed_login_by_email = RateLimiter(limit=8, window_seconds=15 * 60)
#: New accounts from one client address.
register_by_ip = RateLimiter(limit=10, window_seconds=60 * 60)


def reset_all() -> None:
    for limiter in (login_by_ip, failed_login_by_email, register_by_ip):
        limiter.reset()
