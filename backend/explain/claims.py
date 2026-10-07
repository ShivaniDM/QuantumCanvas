"""Deterministic claim checker (plan 9b.2). No model is involved.

It extracts the numbers and the direction words from each piece of LLM text and compares them with the math layer's
step log. Any mismatch -> the LLM text is discarded and the template is shown (the failure is logged as research data).
"""
from __future__ import annotations

import re

NUM_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
NUM_DEC = re.compile(r"(?<![\w.])(\d+\.\d+)(?![\w%]|\.\d)")      # a sentence-ending period is fine
IDENT = re.compile(r"\b[A-Za-z]{1,2}\d+\b")           # q0, Q1, N3 ... are names, not numbers

UP = re.compile(r"\b(more likely|increase[sd]?|rais(?:e|es|ed|ing)|boost(?:s|ed)? (?:the )?(?:chance|probability)|higher|amplif\w+|grows?|rises?)\b", re.I)
DOWN = re.compile(r"\b(less likely|decrease[sd]?|lower(?:s|ed)?|drops?|dropp?ed|reduc\w+|falls?|fell|smaller)\b", re.I)
NOEFFECT = re.compile(r"\b(no effect|has no impact|doesn'?t (?:change|affect)|does not (?:change|affect)|unchanged|nothing changes|no change|did not change|didn'?t change|makes no difference)\b", re.I)
FIFTY = re.compile(r"(50\s*/\s*50|50\s*%|even(?:ly)? (?:split|mix|chance)|equally likely|fifty)", re.I)
ENTANGLED = re.compile(r"\b(entangle(?:d|s|ment)?|correlated|linked|linking)\b", re.I)
SUCCESS = re.compile(r"\b(successfully|works? as (?:expected|intended)|as expected|perfectly|exactly as intended)\b", re.I)
NEGATIVE = re.compile(r"\b(not|n't|no |never|instead|however|but|only|overwr\w+|lower(?:ed|s)|past|too many|falls?|didn'?t|doesn'?t|cannot|can't|unchanged|without|flips?)\b", re.I)

NEGATION = re.compile(r"\b(not|no|never|neither|nor|without|instead of|rather than|fails? to|failed to|unable to|isn'?t|doesn'?t|didn'?t|won'?t|cannot|can'?t)\b|n't\b", re.I)


def _asserts(rx, text: str):
    """The first match of `rx` that is stated positively (not preceded by a negation in the same clause), else None."""
    for m in rx.finditer(text):
        clause = re.split(r"[.;:!?]", text[:m.start()])[-1][-45:]
        if not NEGATION.search(clause):
            return m
    return None


PCT_TOL = 0.6          # percentage points: people round to a whole percent (max error 0.5); the log has 4 decimals
DEC_TOL = 0.006
EPS = 5e-3


def _numbers_allowed(step: dict, n_steps: int, n_qubits: int) -> tuple[set, set]:
    pct, dec = set(), set()
    for k in ("p1_before", "p1_after"):
        pct.update(round(100 * v, 2) for v in step.get(k, []))
    for k in ("entropy_before", "entropy_after"):
        dec.update(v for v in step.get(k, []) if v is not None)
    if step.get("result_shift_if_removed") is not None:
        pct.add(round(100 * step["result_shift_if_removed"], 2))
    for c in step.get("contracts", []):
        detail = c.get("detail", "")
        nums = [float(m) for m in re.findall(r"(?<![\d.])(\d+\.\d+)(?![\d%])", detail)]
        dec.update(nums)
        # only PROBABILITY details become percentages; "entropy q0: 0.000 -> 1.000" is in bits, not 0% -> 100%
        if not detail.lstrip().startswith("entropy"):
            pct.update(round(100 * x, 2) for x in nums if x <= 1.0)
    f = step.get("facts", {}).get("boost")
    if f:
        pct.update(round(100 * x, 2) for x in f["trajectory"])
    pct.update({0.0, 50.0, 100.0} if step["op"] in ("shake",) else set())
    return pct, dec


def _summary_allowed(log: dict, counts: dict | None):
    pct = {round(100 * v, 2) for v in (log.get("predicted") or {}).values()} | {0.0, 100.0}
    total = sum((counts or {}).values()) or 0
    if total:
        pct |= {round(100 * v / total, 2) for v in counts.values()}
    dec = set()
    for c in log["checks"]:
        dec.update(float(m) for m in re.findall(r"(\d+\.\d+)", str(c.get("detail", ""))))
    for s in log["steps"]:
        dec.update(v for v in s.get("entropy_after", []) if v is not None)
        pct.update(round(100 * v, 2) for v in s.get("p1_after", []))
    return pct, dec


def _check_numbers(text, pct_ok, dec_ok, where, out, n_steps=64):
    scrubbed = IDENT.sub(" ", text)
    for m in NUM_PCT.finditer(scrubbed):
        v = float(m.group(1))
        if not any(abs(v - a) <= PCT_TOL for a in pct_ok):
            out.append({"where": where, "type": "number", "claim": m.group(0), "detail": f"{m.group(0)} is not a percentage in the step log for {where}"})
    for m in NUM_DEC.finditer(NUM_PCT.sub(" ", scrubbed)):
        v = float(m.group(1))
        if not any(abs(v - a) <= DEC_TOL for a in dec_ok) and not any(abs(v * 100 - a) <= PCT_TOL for a in pct_ok):
            out.append({"where": where, "type": "number", "claim": m.group(0), "detail": f"{m.group(0)} does not appear in the step log for {where}"})


def _direction(step: dict, op: str):
    """actual direction of the thing the step is about: 'up' | 'down' | 'flat' | None"""
    f = step.get("facts", {}).get("boost")
    if op == "boost" and f:
        d = f["trajectory"][-1] - f["trajectory"][0]
        return "up" if d > EPS else "down" if d < -EPS else "flat"
    ds = [a - b for a, b in zip(step["p1_after"], step["p1_before"])]
    if all(abs(d) <= EPS for d in ds):
        return "flat"
    return "up" if max(ds) > EPS and min(ds) >= -EPS else "down" if min(ds) < -EPS and max(ds) <= EPS else "mixed"


def check_step_text(text: str, step: dict, op: str, n_steps: int, n_qubits: int) -> list[dict]:
    out: list[dict] = []
    where = step["id"]
    pct_ok, dec_ok = _numbers_allowed(step, n_steps, n_qubits)
    _check_numbers(text, pct_ok, dec_ok, where, out)
    broken = [c for c in step.get("contracts", []) if not c["held"]]
    held_claims = " ".join(c["claim"] for c in step.get("contracts", []))
    direction = _direction(step, op)

    up, down, fifty = _asserts(UP, text), _asserts(DOWN, text), _asserts(FIFTY, text)
    if up and direction in ("down", "flat") and not (op in ("mark", "phase")):
        out.append({"where": where, "type": "direction", "claim": up.group(0),
                    "detail": f"the log shows the chance went {'down' if direction == 'down' else 'nowhere'} in {where}"})
    if down and direction in ("up", "flat") and not (op in ("mark", "phase")) and not (op == "boost" and broken):
        out.append({"where": where, "type": "direction", "claim": down.group(0),
                    "detail": f"the log shows the chance went {'up' if direction == 'up' else 'nowhere'} in {where}"})
    if NOEFFECT.search(text):
        quiet = step.get("affects_result") is False or direction == "flat" or op in ("mark", "phase")
        if not quiet and step.get("affects_result") is True:
            out.append({"where": where, "type": "direction", "claim": NOEFFECT.search(text).group(0),
                        "detail": f"{where} does change the measured result (shift {step.get('result_shift_if_removed')})"})
    if fifty and op == "shake" and any(not c["held"] and "50/50" in c["claim"] for c in step.get("contracts", [])):
        out.append({"where": where, "type": "direction", "claim": fifty.group(0), "detail": "the Shake contract (50/50) is broken for this step"})
    ent = _asserts(ENTANGLED, text)
    if ent and op == "entangle" and any(not c["held"] for c in step.get("contracts", [])):
        out.append({"where": where, "type": "direction", "claim": ent.group(0), "detail": "this Entangle did not increase entanglement"})
    if ent and op not in ("entangle", "swap", "control") and all((v or 0) < 0.01 for v in step.get("entropy_after", [0])):
        out.append({"where": where, "type": "direction", "claim": ent.group(0), "detail": f"no entanglement exists after {where}"})
    if broken and SUCCESS.search(text):
        out.append({"where": where, "type": "omission", "claim": SUCCESS.search(text).group(0), "detail": "claims success although a contract is broken"})
    if (broken or step.get("affects_result") is False) and not NEGATIVE.search(text):
        out.append({"where": where, "type": "omission", "claim": text[:80],
                    "detail": "does not mention that " + ("a contract is broken" if broken else "this step doesn't affect the measured result")})
    return out


def check_summary_text(text: str, log: dict, counts: dict | None) -> list[dict]:
    out: list[dict] = []
    pct_ok, dec_ok = _summary_allowed(log, counts)
    _check_numbers(text, pct_ok, dec_ok, "summary", out)
    broken = [s["id"] for s in log["steps"] if any(not c["held"] for c in s["contracts"])]
    if broken and SUCCESS.search(text):
        out.append({"where": "summary", "type": "omission", "claim": SUCCESS.search(text).group(0), "detail": f"claims success although contracts are broken in {', '.join(broken)}"})
    return out


def check_llm_output(parsed: dict, log: dict, doc: dict, counts: dict | None) -> dict:
    """-> {"passed": bool, "violations": [...], "checked_steps": n}. `parsed` is the model's JSON."""
    violations: list[dict] = []
    if not isinstance(parsed, dict) or not isinstance(parsed.get("summary"), str) or not isinstance(parsed.get("steps"), list):
        return {"passed": False, "violations": [{"where": "format", "type": "format", "claim": "", "detail": "reply is not the requested JSON shape"}], "checked_steps": 0}
    steps = {s["id"]: s for s in log["steps"]}
    ops = {o["id"]: o["op"] for o in doc["operations"]}
    seen = set()
    for item in parsed["steps"]:
        sid = item.get("id") if isinstance(item, dict) else None
        text = item.get("text") if isinstance(item, dict) else None
        if sid not in steps or not isinstance(text, str):
            violations.append({"where": str(sid), "type": "unknown_step", "claim": "", "detail": f"step {sid!r} is not in the step log"})
            continue
        seen.add(sid)
        violations += check_step_text(text, steps[sid], ops[sid], len(steps), log["n_qubits"])
    for sid, s in steps.items():                                     # a step with a broken contract may not be silently skipped
        if sid not in seen and (any(not c["held"] for c in s["contracts"]) or s.get("affects_result") is False):
            violations.append({"where": sid, "type": "omission", "claim": "", "detail": f"{sid} has a broken contract or no effect, but the text says nothing about it"})
    violations += check_summary_text(parsed["summary"], log, counts)
    return {"passed": not violations, "violations": violations, "checked_steps": len(seen)}
