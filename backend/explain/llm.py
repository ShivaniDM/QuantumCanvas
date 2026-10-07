"""Provider-agnostic, OpenAI-compatible chat client (plan 9b.3). Providers are configuration, not code.

    LLM_BASE_URL / LLM_API_KEY / LLM_MODEL            primary  (e.g. Cloudflare Workers AI or Groq)
    LLM_FALLBACK_BASE_URL / _API_KEY / _MODEL         optional secondary

Chain: primary -> secondary -> template only. Hitting a quota (HTTP 429/402, "quota"/"rate limit" bodies) or a
provider outage moves to the next link; it never raises into the page. Keys are read server-side only and are
never logged (everything passes through runlog.redact).
"""
from __future__ import annotations

import datetime
import threading
import time
from dataclasses import dataclass

import requests

from runlog.redact import redact_text


class QuotaExceeded(Exception):
    pass


class ProviderError(Exception):
    pass


@dataclass
class Provider:
    label: str
    base_url: str
    api_key: str
    model: str


def configured_providers(settings) -> list[Provider]:
    out = []
    for label, b, k, m in (("primary", settings.LLM_BASE_URL, settings.LLM_API_KEY, settings.LLM_MODEL),
                           ("fallback", settings.LLM_FALLBACK_BASE_URL, settings.LLM_FALLBACK_API_KEY, settings.LLM_FALLBACK_MODEL)):
        if b and k and m:
            out.append(Provider(label, b.rstrip("/"), k, m))
    return out


# ── daily request budget (keeps a free allowance from being burned) ───────
_lock = threading.Lock()
_budget = {"day": None, "used": 0}


def budget_available(limit: int) -> bool:
    if not limit:
        return True
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    with _lock:
        if _budget["day"] != today:
            _budget.update(day=today, used=0)
        return _budget["used"] < limit


def budget_spend():
    with _lock:
        _budget["used"] += 1


def budget_reset():
    with _lock:
        _budget.update(day=None, used=0)


_QUOTA_WORDS = ("quota", "rate limit", "rate_limit", "too many requests", "daily limit", "neurons", "insufficient")


def chat(provider: Provider, messages: list[dict], *, timeout: float = 25.0, max_tokens: int = 900, session=None) -> dict:
    """-> {"text", "tokens": {...}, "latency_ms", "raw"}. Raises QuotaExceeded / ProviderError (messages are redacted)."""
    http = session or requests
    t0 = time.perf_counter()
    try:
        r = http.post(f"{provider.base_url}/chat/completions",
                      headers={"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"},
                      json={"model": provider.model, "messages": messages, "temperature": 0, "max_tokens": max_tokens},
                      timeout=timeout)
    except requests.RequestException as e:
        raise ProviderError(redact_text(f"{provider.label} unreachable: {type(e).__name__}: {e}", [provider.api_key]))
    body = (r.text or "")[:2000]
    if r.status_code in (402, 429) or (r.status_code in (400, 403) and any(w in body.lower() for w in _QUOTA_WORDS)):
        raise QuotaExceeded(redact_text(f"{provider.label} quota/rate limit (HTTP {r.status_code})", [provider.api_key]))
    if r.status_code >= 400:
        raise ProviderError(redact_text(f"{provider.label} returned HTTP {r.status_code}: {body[:300]}", [provider.api_key]))
    try:
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty content")
    except Exception as e:
        raise ProviderError(redact_text(f"{provider.label} sent an unreadable response ({e})", [provider.api_key]))
    usage = data.get("usage") or {}
    return {"text": text, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "raw": data,
            "tokens": {"prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens"), "total": usage.get("total_tokens")}}
