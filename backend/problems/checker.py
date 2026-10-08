"""Problem bank + auto-checker. Problems are data (problems.json); checks are deterministic
(fixed Aer seed, exact statevectors, exhaustive basis inputs)."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np

from concepts import compile_document
from concepts.schema import parse_document, walk

BANK = Path(__file__).with_name("problems.json")
SEED = 1234
SHOTS = 20000


def load_problems() -> list[dict]:
    return json.loads(BANK.read_text(encoding="utf-8"))


def get_problem(pid: str) -> dict | None:
    return next((p for p in load_problems() if p["id"] == pid), None)


def public_view(p: dict) -> dict:
    """What the UI may show: no reference solution or numeric targets."""
    return {k: p[k] for k in ("id", "family", "statement", "qubits", "classical_bits", "allowed_concepts", "hint_ladder", "must_use") if k in p}


# ── helpers ──────────────────────────────────────────────────────────
def _compile(doc: dict):
    return compile_document(doc)


def _with_extras(problem: dict, check: dict, doc: dict) -> dict:
    d = copy.deepcopy(doc)
    ops = [dict(o, id="setup_" + o["id"]) for o in check.get("setup", [])] + d["operations"]
    ops += [dict(o, id="post_" + o["id"]) for o in check.get("postfix", [])]
    d["operations"] = ops
    for o in ops:
        for c in o.get("classical", []) or []:
            d["classical_bits"] = max(d.get("classical_bits", 0), c + 1)
    return d


def _has_measure(doc: dict) -> bool:
    return any(o["op"] == "measure" for o in doc["operations"])


def _unitary_circuit(res):
    from concepts.emit_qiskit import build_circuit
    return build_circuit(res.lowered).remove_final_measurements(inplace=False)


def _matches(node, want) -> bool:
    if isinstance(want, str):
        return node.op == want
    if node.op != want["op"]:
        return False
    for k, v in want.items():
        if k == "op":
            continue
        have = node.params.get(k, False if k == "inverse" else None)
        if have != v:
            return False
    return True


def _counts_to_marginal(counts: dict, marginal: list | None) -> dict:
    out: dict = {}
    total = sum(counts.values())
    for key, c in counts.items():
        n = len(key)
        if marginal:
            k = "".join(key[n - 1 - cb] for cb in sorted(marginal, reverse=True))
        else:
            k = key
        out[k] = out.get(k, 0) + c / total
    return out


# ── individual checks ────────────────────────────────────────────────
def _check_distribution(problem, check, doc):
    from aer_runner import run_aer_circuit
    from concepts.emit_qiskit import build_circuit
    d = _with_extras(problem, check, doc)
    if not _has_measure(d):
        qs = check.get("auto_measure", {}).get("qubits", list(range(d["qubits"])))
        cs = check.get("auto_measure", {}).get("clbits", qs)
        d["operations"].append({"id": "auto_measure", "op": "measure", "targets": qs, "classical": cs})
        d["classical_bits"] = max(d.get("classical_bits", 0), max(cs) + 1)
    res = _compile(d)
    if not res.ok:
        return False, "; ".join(e.message for e in res.errors)
    counts = run_aer_circuit(build_circuit(res.lowered), SHOTS, seed=SEED)
    got = _counts_to_marginal(counts, check.get("marginal_clbits"))
    tol = check.get("tolerance", 0.02)
    problems = []
    for k, want in check.get("target", {}).items():
        if abs(got.get(k, 0.0) - want) > tol:
            problems.append(f"|{k}⟩ came out {got.get(k, 0.0):.1%}, expected {want:.1%} (±{tol:.0%})")
    for k, floor in check.get("at_least", {}).items():
        if got.get(k, 0.0) < floor:
            problems.append(f"|{k}⟩ came out {got.get(k, 0.0):.1%}, needs at least {floor:.0%}")
    if check.get("target") and not problems:
        extra = sum(v for k, v in got.items() if k not in check["target"])
        if extra > tol:
            problems.append(f"{extra:.1%} of the shots landed on outcomes that shouldn't appear")
    top = ", ".join(f"|{k}⟩ {v:.0%}" for k, v in sorted(got.items(), key=lambda kv: -kv[1])[:4])
    return not problems, ("; ".join(problems) if problems else f"measured: {top}")


def _check_statevector(problem, check, doc):
    from qiskit.quantum_info import Statevector
    res = _compile(_with_extras(problem, check, doc))
    if not res.ok:
        return False, "; ".join(e.message for e in res.errors)
    sv = Statevector(_unitary_circuit(res))
    t = check["target"]
    if "basis" in t:
        want = Statevector.from_int(t["basis"], 2 ** problem["qubits"])
    else:
        want = Statevector.from_label(t["label"])
    ok = sv.equiv(want)
    top = max(sv.probabilities_dict().items(), key=lambda kv: kv[1])
    return ok, ("the state is right (global phase ignored)" if ok else f"the state isn't the target; most likely outcome is |{top[0]}⟩ at {top[1]:.0%}")


def _check_unitary(problem, check, doc):
    from qiskit.quantum_info import Operator
    res = _compile(_with_extras(problem, check, doc))
    if not res.ok:
        return False, "; ".join(e.message for e in res.errors)
    got = Operator(_unitary_circuit(res))
    if check.get("target") == "identity":
        want = Operator(np.eye(2 ** problem["qubits"]))
    else:
        ref = _compile(problem["reference_solution"])
        want = Operator(_unitary_circuit(ref))
    ok = got.equiv(want)
    return ok, ("the circuit does the same thing as the reference (global phase ignored)" if ok else "the circuit's overall effect differs from what the problem asks")


def _basis_run(problem, doc, bits_set):
    from qiskit.quantum_info import Statevector
    d = copy.deepcopy(doc)
    prep = [{"id": f"in_{q}", "op": "flip", "targets": [q]} for q in bits_set]
    d["operations"] = prep + d["operations"]
    res = _compile(d)
    if not res.ok:
        return None, "; ".join(e.message for e in res.errors)
    probs = Statevector(_unitary_circuit(res)).probabilities_dict()
    key = max(probs, key=probs.get)
    return (key, probs[key]), None


def _check_classical(problem, check, doc):
    fn = check["function"]
    kind = fn["kind"]
    n = problem["qubits"]
    bit = lambda key, q: int(key[::-1][q])
    val = lambda key, qs: sum(bit(key, q) << i for i, q in enumerate(qs))
    if kind == "const_output":
        (out, perr) = _basis_run(problem, doc, [])
        if perr:
            return False, perr
        key, p = out
        got = val(key, fn["qubits"])
        return (got == fn["value"] and p > 0.999), f"the register holds {got} (needs {fn['value']})"
    ins = fn["input_qubits"] if "input_qubits" in fn else fn["qubits"]
    for v in range(2 ** len(ins)):
        (out, perr) = _basis_run(problem, doc, [q for i, q in enumerate(ins) if (v >> i) & 1])
        if perr:
            return False, perr
        key, p = out
        if p < 0.999:
            return False, f"for input {v} the circuit leaves the register in a mix of answers, not one definite value"
        if kind == "flag_eq":
            want_flag = int(v == fn["value"])
            if bit(key, fn["flag_qubit"]) != want_flag:
                return False, f"for input {v} the flag is {bit(key, fn['flag_qubit'])}, expected {want_flag}"
            if val(key, ins) != v:
                return False, f"for input {v} the register changed to {val(key, ins)}; it should be left alone"
        elif kind == "add_const":
            want = (v + fn["value"]) % fn["modulus"]
            got = val(key, ins)
            if got != want:
                return False, f"for input {v} the register ends at {got}, expected {want}"
        else:
            return False, f"unknown function kind {kind}"
    return True, f"correct for all {2 ** len(ins)} inputs"


def _check_qubit_probs(problem, check, doc):
    from qiskit.quantum_info import Statevector
    res = _compile(_with_extras(problem, check, doc))
    if not res.ok:
        return False, "; ".join(e.message for e in res.errors)
    probs = Statevector(_unitary_circuit(res)).probabilities()
    tol = check.get("tolerance", 0.02)
    msgs, ok = [], True
    for q, want in check["target"].items():
        q = int(q)
        got = sum(p for i, p in enumerate(probs) if (i >> q) & 1)
        msgs.append(f"q{q}: P(1) = {got:.1%} (wants {want:.0%})")
        ok &= abs(got - want) <= tol
    return ok, "; ".join(msgs)


_CHECKS = {"distribution": _check_distribution, "statevector": _check_statevector, "unitary": _check_unitary,
           "classical_function": _check_classical, "qubit_probabilities": _check_qubit_probs}


# ── entry point ──────────────────────────────────────────────────────
def check_solution(problem: dict, solution: dict) -> dict:
    out = {"problem_id": problem["id"], "passed": False, "checks": [], "errors": [], "warnings": [],
           "hint_ladder": problem.get("hint_ladder", [])}

    def fail(msg):
        out["checks"].append({"name": "setup", "passed": False, "detail": msg})
        out["summary"] = msg
        return out

    res = compile_document(solution)
    out["errors"] = [e.to_dict() for e in res.errors]
    out["warnings"] = [w.to_dict() for w in res.warnings]
    if not res.ok:
        return fail("Your circuit has a problem to fix first: " + "; ".join(e.message for e in res.errors))
    if solution["qubits"] != problem["qubits"]:
        return fail(f"This problem uses exactly {problem['qubits']} qubits; your circuit has {solution['qubits']}.")
    doc = parse_document(solution)
    allowed = set(problem.get("allowed_concepts", []))
    nodes = list(walk(doc.operations))
    bad = sorted({n.op for n in nodes if allowed and n.op not in allowed})
    if bad:
        return fail("This problem only allows: " + ", ".join(sorted(allowed)) + f". You used: {', '.join(bad)}.")
    for want in problem.get("must_use", []):
        if not any(_matches(n, want) for n in nodes):
            label = want if isinstance(want, str) else (("inverse " if want.get("inverse") else "") + want["op"])
            out["checks"].append({"name": f"uses {label}", "passed": False, "detail": f"The problem is about {label}; use it in your circuit."})
    if any(not c["passed"] for c in out["checks"]):
        out["summary"] = out["checks"][0]["detail"]
        return out

    chk = problem["check"]
    ok, detail = _CHECKS[chk["type"]](problem, chk, solution)
    out["checks"].append({"name": chk["type"].replace("_", " "), "passed": bool(ok), "detail": detail})
    for extra in chk.get("also", []):
        ok2, d2 = _CHECKS[extra["type"]](problem, extra, solution)
        out["checks"].append({"name": extra["type"].replace("_", " "), "passed": bool(ok2), "detail": d2})
    out["passed"] = all(c["passed"] for c in out["checks"])
    out["summary"] = "Solved!" if out["passed"] else next(c["detail"] for c in out["checks"] if not c["passed"])
    return out
