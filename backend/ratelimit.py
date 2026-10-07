"""Minimal in-memory per-IP rate limit for the expensive routes.

Not a replacement for real infrastructure (it resets on restart and isn't shared across
multiple instances) — it exists so one client can't monopolize or exhaust a single
server instance by hammering /execute, /cost or /compile. Swap for a Redis-backed
limiter (or your platform's own) before scaling to more than one instance.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import settings

_LIMITED_PATHS = ("/execute", "/cost", "/compile")
_WINDOW_S = 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reads settings.RATE_LIMIT_PER_MINUTE on every request (not once at startup), so the test
    suite can set it to 0 (disabled) without needing to reconstruct the app."""

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next):
        limit = settings.RATE_LIMIT_PER_MINUTE
        if limit and request.url.path in _LIMITED_PATHS:
            client = request.client.host if request.client else "unknown"
            now = time.monotonic()
            with self._lock:
                q = self._hits[client]
                while q and now - q[0] > _WINDOW_S:
                    q.popleft()
                if len(q) >= limit:
                    return JSONResponse({"detail": "Too many requests — slow down and try again shortly."},
                                        status_code=429)
                q.append(now)
        return await call_next(request)
