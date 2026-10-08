"""One-step explanation (the "?" button): the exact maths for the step, the deterministic template sentence, and an
optional LLM paragraph that must pass the same claim checker as the whole-run explanation.

The model is only a narrator. It is handed the step's computed maths (kets, probabilities, contracts) and its text is
checked against the step log before anyone sees it; if it contradicts the maths it is thrown away.
"""
from __future__ import annotations

import hashlib
import json

from . import claims, llm
from .service import LABEL, _parse_json, template_explanation

_cache: dict[str, dict] = {}

SYSTEM = """You explain ONE step of a small quantum circuit to a beginner. You are given the exact maths for that step,
computed by simulation. A program checks your reply against it; a reply that contradicts it is thrown away.
Rules:
1. Use only facts in the data. Never invent numbers. Write probabilities as percentages exactly as given.
2. You may quote amplitudes and kets ONLY exactly as written in the data (for example 1/√2, |00⟩). Never write decimals such as 0.707.
3. Explain in this order, in 3-5 short sentences: what the step does, what the matrix/equation means for the state shown
   (before -> after), and what that means for the chance of seeing 0 or 1.
4. If a contract is BROKEN (held=false) or affects_measured_result is false, say so plainly and why.
5. No jargon without a few words of explanation. Refer to qubits by the names in "qubit_names".
Reply with JSON only, no markdown: {"text": "<your explanation>"}"""


def _step_payload(step_log: dict, sm: dict, labels: list[str], n: int) -> dict:
    after = sm.get("after", {}).get("branches", [])
    before = sm.get("before", {}).get("branches", [])
    view = lambda bs: [{"probability_percent": round(100 * b["prob"], 2), "state": b["ket"], "classical_bits": b["bits"] or None} for b in bs]
    return {"qubit_names": labels, "ket_order": "rightmost digit is " + (labels[0] if labels else "Q1"),
            "concept": step_log["op"], "targets": sm.get("target_names"), "equation": sm.get("equation"),
            "gate_matrix": sm.get("matrix"), "gate_matrix_acts_on": sm.get("local_qubits"),
            "basis_actions": [f"|{a['from']}⟩ -> {a['to']}" for a in sm.get("action", [])],
            "state_before": view(before), "state_after": view(after),
            "chance_of_1_before": {labels[i]: v for i, v in enumerate(step_log["p1_before"])},
            "chance_of_1_after": {labels[i]: v for i, v in enumerate(step_log["p1_after"])},
            "affects_measured_result": step_log.get("affects_result"),
            "contracts": step_log.get("contracts", []), "facts": step_log.get("facts", {})}


def explain_step(log: dict, doc: dict, step_id: str, sm: dict, counts, labels, settings, use_llm=True, session=None) -> dict:
    tmpl_all = template_explanation(log, doc, counts, labels)
    t = next((s for s in tmpl_all["steps"] if s["id"] == step_id), None)
    step_log = next((s for s in log["steps"] if s["id"] == step_id), None)
    out = {"step_id": step_id, "template": t, "math": sm,
           "llm": {"label": LABEL, "status": "not_requested", "text": None, "attempts": []}}
    if not use_llm or step_log is None:
        return out
    L = out["llm"]
    providers = llm.configured_providers(settings)
    if not providers:
        L["status"] = "unconfigured"
        return out
    payload = _step_payload(step_log, sm, labels, log["n_qubits"])
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "STEP DATA:\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]
    key = hashlib.sha256(json.dumps([messages, [(p.base_url, p.model) for p in providers]], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if key in _cache:
        return {**out, "llm": {**_cache[key], "cache_hit": True}}
    if not llm.budget_available(settings.LLM_DAILY_REQUEST_BUDGET):
        L.update(status="budget", attempts=[{"provider": "-", "error": "daily request budget used up"}])
        return out
    for i, p in enumerate(providers):
        try:
            llm.budget_spend()
            resp = llm.chat(p, messages, timeout=settings.LLM_TIMEOUT_S, max_tokens=500, session=session)
        except llm.QuotaExceeded as e:
            L["attempts"].append({"provider": p.label, "kind": "quota", "error": str(e)[:300]})
            continue
        except llm.ProviderError as e:
            L["attempts"].append({"provider": p.label, "kind": "unavailable", "error": str(e)[:300]})
            continue
        parsed = _parse_json(resp["text"])
        text = parsed.get("text") if isinstance(parsed, dict) else None
        if not isinstance(text, str) or not text.strip():
            L.update(status="rejected", provider=p.label, model=p.model, claim_check={"passed": False, "violations": [
                {"where": "format", "type": "format", "claim": "", "detail": "reply is not the requested JSON"}]})
            return out
        one_log = {**log, "steps": [step_log], "checks": []}
        check = claims.check_llm_output({"summary": "", "steps": [{"id": step_id, "text": text}]}, one_log, doc, counts)
        L.update(provider=p.label, model=p.model, tokens=resp["tokens"], latency_ms=resp["latency_ms"], claim_check=check,
                 fallback_used=i > 0, attempts=L["attempts"] + [{"provider": p.label, "ok": True}])
        if check["passed"]:
            L.update(status="ok", text=text.strip())
            _cache[key] = {k: L[k] for k in L}
        else:
            L.update(status="rejected", text=None)
        return out
    L["status"] = "unavailable"
    return out
