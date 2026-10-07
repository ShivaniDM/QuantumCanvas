"""Explanation service: template first (always), optional LLM text that must pass the claim checker (plan 9b)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import claims, llm, prompt
from .template import UNMEASURED_WARNING, idle_steps, pct, render_step

LABEL = "AI explanation, grounded in simulation"
_mem_cache: dict[str, dict] = {}


def template_explanation(log: dict, doc: dict, counts: dict | None, labels: list[str]) -> dict:
    """Rendered from the step log; every sentence is backed by a log field. Always available, never needs a key."""
    from concepts.emit_pseudocode import build_pseudocode
    from concepts.schema import parse_document
    ops = {o["id"]: o for o in doc["operations"]}
    lab = lambda q: labels[q] if q < len(labels) else f"q{q}"
    named = lambda t: re.sub(r"\bq(\d+)\b", lambda m: lab(int(m.group(1))), t)
    base = {st["id"]: st for st in build_pseudocode(parse_document(doc))["steps"] if st["id"]}
    steps = []
    for s in log["steps"]:
        r = render_step(s, ops[s["id"]], lab)
        generic = named(base[s["id"]]["plain"]) if s["id"] in base else ""
        text = " ".join(x for x in (r["plain"] or generic, ("Result: " + r["effect"]) if r["effect"] else "") if x).strip()
        title = named(base[s["id"]]["code"].split("  →")[0]) if s["id"] in base else s["id"]
        if s.get("affects_result") is False and log.get("ineffective_together"):
            text = (text + " " + "Removing this step wouldn't change your result.").strip()
        steps.append({"id": s["id"], "title": title, "concept": s["op"], "text": text, "claim_ok": r["claim_ok"],
                      "affects_result": s.get("affects_result"), "contracts": s.get("contracts", [])})
    return {"summary": _template_summary(log, counts), "steps": steps}


def _template_summary(log: dict, counts: dict | None) -> str:
    bits = []
    pred = log.get("predicted") or {}
    if pred:
        top = sorted(pred.items(), key=lambda kv: -kv[1])[:3]
        bits.append("Exact simulation predicts " + ", ".join(f"|{k}⟩ {pct(v)}" for k, v in top) + ".")
    total = sum((counts or {}).values())
    obs = next((c for c in log["checks"] if c["check"].startswith("observed")), None)
    if total and obs:
        bits.append(("The counts you got agree with that prediction (" if obs["ok"] else "The counts you got do NOT agree with that prediction (")
                     + obs.get("detail", "") + ").")
    idle = idle_steps(log)
    if idle:
        bits.append(f"{len(idle)} of {len(log['steps'])} steps ({', '.join(idle)}) don't change what you measured.")
    broken = [s["id"] for s in log["steps"] if any(not c["held"] for c in s["contracts"])]
    if broken:
        bits.append(f"Steps {', '.join(broken)} did not do what their usual one-line description says; the notes below explain what happened instead.")
    return " ".join(bits) or "No measurement was part of this circuit, so there is no result to compare with."


# ── LLM ──────────────────────────────────────────────────────────────
def _parse_json(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _cache_file(settings, key):
    d = Path(settings.LOG_DIR) / "explain_cache"
    return d / f"{key}.json"


def cache_key(doc, counts, providers, labels) -> str:
    blob = json.dumps({"ir": doc, "counts": counts, "labels": labels, "pv": prompt.PROMPT_VERSION,
                       "models": [(p.base_url, p.model) for p in providers]}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def llm_explanation(log: dict, doc: dict, counts: dict | None, labels: list[str], settings, session=None) -> dict:
    providers = llm.configured_providers(settings)
    out = {"label": LABEL, "status": "unconfigured", "text": None, "provider": None, "model": None, "prompt_hash": None,
           "tokens": None, "latency_ms": None, "cache_hit": False, "fallback_used": False, "claim_check": None,
           "attempts": [], "prompt": None, "response": None}
    if not providers:
        return out
    messages = prompt.build_messages(log, doc, counts, labels)
    out["prompt_hash"], out["prompt"] = prompt.prompt_hash(messages), messages
    key = cache_key(doc, counts, providers, labels)
    if key in _mem_cache or _cache_file(settings, key).exists():
        try:
            hit = _mem_cache.get(key) or json.loads(_cache_file(settings, key).read_text(encoding="utf-8"))
            _mem_cache[key] = hit
            return {**out, **hit, "cache_hit": True}
        except Exception:
            pass
    if not llm.budget_available(settings.LLM_DAILY_REQUEST_BUDGET):
        out.update(status="budget", attempts=[{"provider": "-", "error": "daily request budget used up; showing the template"}])
        return out
    for i, p in enumerate(providers):
        try:
            llm.budget_spend()
            resp = llm.chat(p, messages, timeout=settings.LLM_TIMEOUT_S, session=session)
        except llm.QuotaExceeded as e:
            out["attempts"].append({"provider": p.label, "model": p.model, "error": str(e), "kind": "quota"})
            continue
        except llm.ProviderError as e:
            out["attempts"].append({"provider": p.label, "model": p.model, "error": str(e), "kind": "unavailable"})
            continue
        out.update(provider=p.label, model=p.model, tokens=resp["tokens"], latency_ms=resp["latency_ms"],
                   response=resp["text"], fallback_used=i > 0)
        out["attempts"].append({"provider": p.label, "model": p.model, "ok": True})
        parsed = _parse_json(resp["text"])
        check = claims.check_llm_output(parsed, log, doc, counts) if parsed is not None else \
            {"passed": False, "violations": [{"where": "format", "type": "format", "claim": "", "detail": "reply is not valid JSON"}], "checked_steps": 0}
        out["claim_check"] = check
        if check["passed"]:
            out.update(status="ok", text=parsed)
            cacheable = {k: out[k] for k in ("status", "text", "provider", "model", "tokens", "latency_ms", "claim_check", "fallback_used", "response", "prompt_hash", "attempts")}
            _mem_cache[key] = cacheable
            try:
                f = _cache_file(settings, key); f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(cacheable, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        else:
            out.update(status="rejected", text=None)          # the contradicting text is NEVER shown; the failure is logged
        return out
    out["status"] = "unavailable"
    return out


def explain(log: dict, doc: dict, counts: dict | None, labels: list[str], settings, use_llm=True, session=None) -> dict:
    labels = labels or [f"q{i}" for i in range(doc["qubits"])]
    res = {"template": template_explanation(log, doc, counts, labels), "llm": None}
    res["llm"] = llm_explanation(log, doc, counts, labels, settings, session) if use_llm else \
        {"label": LABEL, "status": "not_requested", "text": None}
    return res
