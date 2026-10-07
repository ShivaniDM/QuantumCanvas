"""Per-step quantum maths for the "Math" tab: exact amplitudes in Dirac (bra-ket) notation, gate matrices,
what each gate does to every basis state, and the matrix-times-vector calculation.

Everything here is computed, never written by a model. It reuses the same exact simulation (`Sim`) and the same
reference semantics (`ref_circuit`) as the math layer, so the Math tab can never disagree with the checks.

Reading kets: |q_n ... q_2 q_1⟩ with the RIGHTMOST digit = Q1 (the same order as the measured result labels).
"""
from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator, Statevector

from .layer import (TOL, NonUnitary, Sim, Unsupported, _touches, normalise_ir, ref_circuit)

MAX_NOTATION_QUBITS = 12     # beyond this the state has too many terms to show
MAX_LOCAL = 3                # largest gate matrix drawn (8 x 8)
MAX_PRODUCT_QUBITS = 3       # full "U . state = new state" shown up to 8 x 8
MAX_TERMS = 32
MAX_BRANCHES = 16
ORDER_NOTE = "Kets are written |Qn … Q2 Q1⟩: the rightmost digit is Q1 (the same order as your measured results)."


# ───────────────────────── exact-looking number formatting ─────────────────────────
def _sqrt_parts(k: int):
    """k = a² · b with b square-free -> (a, b)."""
    a, b, f = 1, k, 2
    while f * f <= b:
        while b % (f * f) == 0:
            b //= f * f
            a *= f
        f += 1
    return a, b


def fmt_real(v: float) -> str:
    """0, 1, 1/2, 1/√2, 1/(2√2), √2 ... when the value is that simple, else 4 decimals."""
    if abs(v) < 1e-10:
        return "0"
    sign = "−" if v < 0 else ""
    x = abs(v)
    r = Fraction(x * x).limit_denominator(1024)
    if abs(float(r) - x * x) > 1e-9:
        return sign + f"{x:.4f}".rstrip("0").rstrip(".")
    a, b = _sqrt_parts(r.numerator)
    c, d = _sqrt_parts(r.denominator)
    rad = lambda k: f"√{k}"
    if d == 1:                                            # a√b / c
        top = (str(a) if a > 1 or b == 1 else "") + (rad(b) if b > 1 else "")
        return sign + (top if c == 1 else f"{top}/{c}")
    if b == 1:                                            # a / (c√d)
        den = rad(d) if c == 1 else f"{c}{rad(d)}"
        return sign + (f"{a}/{den}" if c == 1 else f"{a}/({den})")
    e, f = _sqrt_parts(b * d)                             # both radicals: rationalise
    top = (str(a * e) if a * e > 1 else "") + (rad(f) if f > 1 else "")
    den = c * d
    return sign + (top if den == 1 else f"{top or '1'}/{den}")


def fmt_complex(z: complex) -> str:
    re, im = float(z.real), float(z.imag)
    if abs(im) < 1e-10:
        return fmt_real(re)
    ims = fmt_real(abs(im))
    i_part = "i" if ims == "1" else ("i" + ims[1:] if ims.startswith("1/") else ims + "i")
    if abs(re) < 1e-10:
        return ("−" if im < 0 else "") + i_part
    return f"{fmt_real(re)} {'−' if im < 0 else '+'} {i_part}"


def _is_real(z) -> bool:
    return abs(z.imag) < 1e-10


# ───────────────────────── states in ket notation ─────────────────────────
def basis(i: int, n: int) -> str:
    return format(i, f"0{n}b")


def terms_of(sv_data: np.ndarray, n: int) -> tuple[list[dict], bool]:
    out = []
    for i, a in enumerate(sv_data):
        p = float(abs(a) ** 2)
        if p > 1e-9:
            out.append({"basis": basis(i, n), "amp": fmt_complex(a), "re": float(a.real),
                        "im": float(a.imag), "prob": round(p, 6)})
    truncated = len(out) > MAX_TERMS
    if truncated:
        out = sorted(out, key=lambda t: -t["prob"])[:MAX_TERMS]
        out.sort(key=lambda t: t["basis"])
    return out, truncated


def ket_string(terms: list[dict]) -> str:
    """(|00⟩ + |11⟩)/√2 when every amplitude has the same size and is real, else a sum of coefficient·ket."""
    if not terms:
        return "0"
    if all(abs(t["im"]) < 1e-9 for t in terms):
        mags = {round(abs(t["re"]), 6) for t in terms}
        if len(mags) == 1:
            common = fmt_real(abs(terms[0]["re"]))
            body = ""
            for k, t in enumerate(terms):
                neg = t["re"] < 0
                body += (("−" if neg else "") if k == 0 else (" − " if neg else " + ")) + f"|{t['basis']}⟩"
            if common == "1":
                return body if len(terms) == 1 else body
            if len(terms) == 1:
                return f"{('−' if terms[0]['re'] < 0 else '')}{common}|{terms[0]['basis']}⟩".replace("−−", "−")
            return f"({body})/{common[2:]}" if common.startswith("1/") else f"{common}({body})"
    parts = []
    for k, t in enumerate(terms):
        amp = t["amp"]
        multi = " + " in amp or (" − " in amp)
        neg = amp.startswith("−") and not multi
        mag = amp[1:] if neg else amp
        coef = "" if mag == "1" else (f"({mag})" if multi else mag)
        piece = f"{coef}|{t['basis']}⟩"
        parts.append((" − " if neg else " + ") + piece if k else ("−" if neg else "") + piece)
    return "".join(parts)


def _branch_view(pr, sv, cl, n):
    terms, trunc = terms_of(sv.data, n)
    return {"prob": round(float(pr), 6), "bits": "".join(str(b) for b in reversed(cl)) if cl else "",
            "terms": terms, "ket": ket_string(terms), "truncated": trunc}


def _branches_view(branches, n):
    shown = sorted(branches, key=lambda b: -b[0])[:MAX_BRANCHES]
    return {"branches": [_branch_view(p, s, c, n) for p, s, c in shown], "n_branches": len(branches),
            "truncated": len(branches) > MAX_BRANCHES}


# ───────────────────────── gate matrices ─────────────────────────
def _local_unitary(qc: QuantumCircuit, n: int):
    used = sorted(q for q in range(n) if _touches(qc, q))
    if not used:
        return used, None
    if len(used) > MAX_LOCAL:
        return used, "too_large"
    idx = {q: i for i, q in enumerate(used)}
    sub = QuantumCircuit(len(used))
    for ins in qc.data:
        sub.append(ins.operation, [idx[qc.find_bit(x).index] for x in ins.qubits])
    return used, Operator(sub).data


def _matrix_view(M: np.ndarray) -> list[list[str]]:
    return [[fmt_complex(x) for x in row] for row in M]


def _action_lines(M: np.ndarray, k: int) -> list[dict]:
    """U|b⟩ for every basis state b (the columns of the matrix)."""
    out = []
    for b in range(2 ** k):
        terms, _ = terms_of(M[:, b], k)
        out.append({"from": basis(b, k), "to": ket_string(terms)})
    return out


def _equation(node: dict, labels: list[str]) -> str:
    op, p = node["op"], node.get("params") or {}
    lab = lambda i: labels[i] if i < len(labels) else f"q{i}"
    if op == "shake":
        return "H|0⟩ = (|0⟩ + |1⟩)/√2      H|1⟩ = (|0⟩ − |1⟩)/√2      (applied to each target)"
    if op == "flip":
        return "X|0⟩ = |1⟩      X|1⟩ = |0⟩"
    if op == "set" or (op == "encode" and p.get("method") == "basis"):
        return f"Prepare the basis state |{p.get('value', p.get('data'))}⟩ by flipping the qubits whose bit is 1 (X gates)."
    if op == "encode":
        return "Ry(θ)|0⟩ = cos(θ/2)|0⟩ + sin(θ/2)|1⟩, with θ chosen so that the chance of 1 equals the data value"
    if op == "phase":
        return "P(φ) = diag(1, e^{iφ}):  |0⟩ → |0⟩,  |1⟩ → e^{iφ}|1⟩  (changes only the phase, not the probabilities)"
    if op == "rotate":
        return f"R{p.get('axis', '?')}(φ) = exp(−i·φ·σ{p.get('axis', '?')}/2)"
    if op == "swap":
        return "SWAP|a b⟩ = |b a⟩"
    if op == "entangle":
        return ("CZ|a,b⟩ = (−1)^{a·b}|a,b⟩" if p.get("style") == "cz" else "CNOT|a,b⟩ = |a, a⊕b⟩   (flip b when a = 1)")
    if op == "mark":
        return f"|x⟩ → −|x⟩ when x = {p.get('value', 'the compared value')}; every other |x⟩ unchanged (a hidden sign flip)"
    if op == "boost":
        return "Boost = H^{⊗n}(2|0⟩⟨0| − I)H^{⊗n}  (up to a global sign): reflect every amplitude about the average"
    if op == "measure":
        return "P₀ = |0⟩⟨0|,  P₁ = |1⟩⟨1|;   chance of outcome b = ⟨ψ|P_b|ψ⟩;   state collapses to P_b|ψ⟩ / √chance"
    if op == "reset":
        return "Measure, then flip back to |0⟩ if the result was 1"
    if op == "fourier":
        return "QFT|j⟩ = (1/√N) Σ_k e^{2πi·jk/N}|k⟩"
    if op == "add":
        return f"|x⟩ → |x + {p.get('value')} mod 2^m⟩"
    if op == "compare":
        return "|x⟩|0⟩ → |x⟩|x = value⟩   (flag qubit flips when the register equals the value)"
    if op == "control":
        return "Apply the inner step only when all control qubits are 1: |c⟩|ψ⟩ → |c⟩ U^c |ψ⟩"
    if op == "uncompute":
        return "Undo an earlier step by applying its inverse U†"
    if op == "correct":
        return "Apply the inner step only if the stored measurement bit equals the required value"
    return ""


def _col(vec, n):
    return [fmt_complex(x) for x in vec]


def step_math(doc: dict, labels: list[str] | None = None) -> dict:
    ir = normalise_ir(doc)
    n = ir["qubits"]
    labels = labels or [f"Q{i + 1}" for i in range(n)]
    out = {"n_qubits": n, "labels": labels, "order_note": ORDER_NOTE, "steps": []}
    if n > MAX_NOTATION_QUBITS:
        out["skipped"] = f"{n} qubits is too many to write out the state ({MAX_NOTATION_QUBITS} is the limit)."
        return out
    sim = Sim(ir)
    branches = sim.initial()
    out["initial"] = _branches_view(branches, n)
    ok = True
    for node in ir["operations"]:
        row = {"id": node["id"], "op": node["op"], "targets": node["targets"],
               "target_names": [labels[t] if t < len(labels) else f"q{t}" for t in node["targets"]],
               "equation": _equation(node, labels)}
        if not ok:
            row["unavailable"] = "An earlier step could not be simulated exactly, so this one is skipped."
            out["steps"].append(row)
            continue
        before = branches
        try:
            branches = sim.step(before, node)
        except (Unsupported, NonUnitary) as e:
            ok = False
            row["unavailable"] = f"No exact reference semantics for this step: {e}"
            out["steps"].append(row)
            continue
        row["before"], row["after"] = _branches_view(before, n), _branches_view(branches, n)
        op = node["op"]
        if op == "measure":
            qs = []
            for q in node["targets"]:
                p1 = sum(pr * float(np.sum(np.abs(sv.data[(np.arange(2 ** n) >> q) & 1 == 1]) ** 2)) for pr, sv, _ in before)
                qs.append({"qubit": labels[q] if q < len(labels) else f"q{q}", "p0": round(1 - p1, 6), "p1": round(p1, 6)})
            row["measure"] = qs
        elif op == "reset":
            row["measure"] = None
        else:
            try:
                qc = ref_circuit(node, n, sim.by_id)
            except (Unsupported, NonUnitary):
                qc = None
            if qc is not None:
                used, M = _local_unitary(qc, n)
                row["local_qubits"] = [labels[q] if q < len(labels) else f"q{q}" for q in used]
                if M is None:
                    row["identity"] = True
                elif isinstance(M, str):
                    row["too_large"] = {"qubits": len(used), "dim": 2 ** len(used)}
                else:
                    row["matrix"] = _matrix_view(M)
                    row["basis"] = [basis(b, len(used)) for b in range(2 ** len(used))]
                    row["action"] = _action_lines(M, len(used))
                if n <= MAX_PRODUCT_QUBITS and len(before) == 1 and len(branches) == 1 and op != "correct":
                    U = Operator(qc).data
                    row["product"] = {"U": _matrix_view(U), "before": _col(before[0][1].data, n),
                                      "after": _col(branches[0][1].data, n), "basis": [basis(b, n) for b in range(2 ** n)]}
        out["steps"].append(row)
    return out
