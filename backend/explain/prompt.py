"""Prompt construction (plan 9b.2). The model sees the STEP LOG, never raw amplitudes, and is told to cite only it."""
from __future__ import annotations

import hashlib
import json

PROMPT_VERSION = "1"

SYSTEM = """You explain a small quantum circuit to a beginner. You are given a verified STEP LOG computed by exact simulation.
Rules (they are checked by a program; a reply that breaks them is thrown away):
1. State only facts that appear in the step log. Never invent or round to a number that is not in it.
2. Every number you write must belong to the step you are writing about (probabilities as percentages, entropy in bits).
3. If a step's contract is BROKEN (held=false) or affects_result is false, say so plainly and explain why using the log's detail.
4. Do not say a step makes something "more likely", "50/50" or "entangled" unless the log shows exactly that for that step.
5. Be short: one or two plain sentences per step. No jargon without a word of explanation. Refer to qubits by the names in "qubit_names".
Reply with JSON only, no markdown:
{"summary": "<2-3 sentences about the whole circuit and its result>", "steps": [{"id": "<step id from the log>", "text": "<explanation>"}]}"""


def compact_log(log: dict, doc: dict, counts: dict | None, labels: list[str]) -> dict:
    ops = {o["id"]: o for o in doc["operations"]}
    steps = []
    for s in log["steps"]:
        o = ops.get(s["id"], {})
        steps.append({"id": s["id"], "concept": s["op"], "targets": [labels[t] for t in s["targets"] if t < len(labels)],
                      "chance_of_1_before": {labels[i]: v for i, v in enumerate(s["p1_before"])},
                      "chance_of_1_after": {labels[i]: v for i, v in enumerate(s["p1_after"])},
                      "entanglement_bits_after": {labels[i]: v for i, v in enumerate(s["entropy_after"]) if v is not None},
                      "affects_measured_result": s.get("affects_result"),
                      "result_shift_if_removed": s.get("result_shift_if_removed"),
                      "contracts": s.get("contracts", []), "facts": s.get("facts", {}),
                      "params": {k: v for k, v in (o.get("params") or {}).items()}})
    total = sum((counts or {}).values()) or 0
    return {"qubit_names": labels, "steps": steps, "predicted_distribution": log.get("predicted"),
            "observed_fractions": ({k: round(v / total, 4) for k, v in counts.items()} if total else None),
            "checks": [{"check": c["check"], "ok": c["ok"], "detail": c.get("detail")} for c in log["checks"] if not c["check"].startswith("code matches")],
            "code_matches_circuit": all(c["ok"] for c in log["checks"] if c["check"].startswith("code matches")) if any(c["check"].startswith("code matches") for c in log["checks"]) else None}


def build_messages(log, doc, counts, labels) -> list[dict]:
    payload = compact_log(log, doc, counts, labels)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "STEP LOG:\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]


def prompt_hash(messages) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
