from __future__ import annotations

import time

import requests

from config import settings


class EngineUnavailable(RuntimeError):
    pass


class EngineRequestError(ValueError):
    pass


_http = None
_cache: dict = {}
LISTING_TTL_S = 300


def use_transport(http):
    global _http
    _http = http
    _cache.clear()


def configured() -> bool:
    return bool(settings.ENGINE_URL and settings.ENGINE_API_KEY)


def _call(method: str, path: str, json_body=None, timeout: float | None = None):
    if not configured():
        raise EngineUnavailable("The compile engine isn't set up on this server (ENGINE_URL / ENGINE_API_KEY), "
                                "so only the built-in simulator is available.")
    http = _http or requests
    url = settings.ENGINE_URL.rstrip("/") + path
    try:
        r = http.request(method, url, json=json_body, headers={"X-API-Key": settings.ENGINE_API_KEY},
                         timeout=timeout or settings.ENGINE_TIMEOUT_S)
    except Exception as e:
        raise EngineUnavailable(f"The compile engine can't be reached right now ({type(e).__name__}).") from e
    if r.status_code >= 500 or r.status_code in (401, 403, 429):
        detail = _detail(r)
        if r.status_code in (401, 403):
            detail = f"This server's engine key was refused: {detail}"
        raise EngineUnavailable(detail)
    if r.status_code >= 400:
        raise EngineRequestError(_detail(r))
    return r.json()


def _detail(r) -> str:
    try:
        d = r.json().get("detail")
        if isinstance(d, str):
            return d
    except Exception:
        pass
    return f"The compile engine answered {r.status_code}."


def backends() -> dict:
    ck = ("backends", settings.ENGINE_URL, settings.ENGINE_API_KEY)
    hit = _cache.get(ck)
    if hit and configured() and time.monotonic() - hit[0] < LISTING_TTL_S:
        return hit[1]
    data = _call("GET", "/v1/backends", timeout=30)
    _cache[ck] = (time.monotonic(), data)
    return data


def backend(backend_id: str) -> dict:
    return _call("GET", f"/v1/backends/{backend_id}", timeout=60)


def compile(body: dict) -> dict:
    return _call("POST", "/v1/compile", body)


def run(body: dict) -> dict:
    return _call("POST", "/v1/run", body)
