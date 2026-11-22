"""Small process-local abuse controls for the single-process academic deployment."""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque


class InMemoryWindowLimiter:
    """A bounded sliding-window limiter; use an edge proxy for multi-worker deployments."""

    def __init__(self, max_keys: int = 10_000) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def _prune(self, key: str, now: float, window_seconds: int) -> deque[float]:
        events = self._events[key]
        cutoff = now - window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def retry_after(self, key: str, limit: int, window_seconds: int) -> int | None:
        now = time.monotonic()
        with self._lock:
            events = self._prune(key, now, window_seconds)
            if len(events) < limit:
                return None
            if len(self._events) > self._max_keys:
                expired = [candidate for candidate, values in self._events.items()
                           if not values or values[-1] <= now - max(window_seconds, 3600)]
                for candidate in expired:
                    self._events.pop(candidate, None)
                while len(self._events) > self._max_keys:
                    self._events.pop(next(iter(self._events)))
            return max(1, math.ceil(window_seconds - (now - events[0])))

    def record(self, key: str) -> None:
        with self._lock:
            self._events[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def reset(self) -> None:
        """Clear all buckets; intended for isolated tests only."""
        with self._lock:
            self._events.clear()


login_limiter = InMemoryWindowLimiter()
registration_limiter = InMemoryWindowLimiter()

