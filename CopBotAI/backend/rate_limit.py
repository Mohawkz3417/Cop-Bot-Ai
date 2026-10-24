"""
Minimal in-memory rate limiter (sliding window), zero extra dependencies.

Good enough for a single-process student/demo deployment. For a real
multi-worker production deployment behind a load balancer, swap this for
a Redis-backed limiter (e.g. `slowapi` + `redis`) — the call site in
main.py is a single dependency, so the swap is a one-file change.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from backend.config import settings


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window_seconds:
                q.popleft()
            if len(q) >= self.max_requests:
                retry_after = int(self.window_seconds - (now - q[0])) + 1
                return False, retry_after
            q.append(now)
            return True, 0


chat_limiter = SlidingWindowRateLimiter(
    max_requests=settings.RATE_LIMIT_MAX_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
)


def enforce_rate_limit(request: Request) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = chat_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests — please wait {retry_after}s and try again.",
            headers={"Retry-After": str(retry_after)},
        )
