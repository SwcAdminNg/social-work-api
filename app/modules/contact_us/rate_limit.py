"""In-memory sliding-window limiter for the public contact form.

Good enough for a single API instance: it stops a burst of repeated submissions
from one address or for one sender email. Limits reset if the process restarts,
and each instance keeps its own counts if the API is ever scaled out.
"""

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Records an attempt for `key`. Returns False when the limit is exceeded."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            # Drop empty keys now and then so the map cannot grow without bound.
            if len(self._hits) > 10_000:
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


contact_limiter = SlidingWindowLimiter()
