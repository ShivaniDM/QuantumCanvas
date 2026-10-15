from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import settings

_HEAVY_PATHS = ("/execute", "/cost", "/transpile", "/code-help")
_LIGHT_PATHS = ("/compile", "/import", "/math", "/explain", "/explain-step")
_WINDOW_S = 60


class RateLimitMiddleware(BaseHTTPMiddleware):

    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        heavy = path in _HEAVY_PATHS
        limit = settings.RATE_LIMIT_PER_MINUTE if heavy else settings.RATE_LIMIT_LIGHT_PER_MINUTE
        if limit and request.method == "POST" and (heavy or path in _LIGHT_PATHS):
            client = request.client.host if request.client else "unknown"
            now = time.monotonic()
            with self._lock:
                q = self._hits[(client, heavy)]
                while q and now - q[0] > _WINDOW_S:
                    q.popleft()
                if len(q) >= limit:
                    return JSONResponse({"detail": "Too many requests — slow down and try again shortly."},
                                        status_code=429)
                q.append(now)
        return await call_next(request)
