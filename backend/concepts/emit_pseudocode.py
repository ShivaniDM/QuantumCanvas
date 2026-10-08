"""Concept IR -> learner-readable steps. Shape matches what the existing
pseudocode panel renders: {n, op, targets, code, plain, qnote}."""
from __future__ import annotations

from .angles import pi_multiple, to_rad
from .schema import Document, Node


def _q(qs):
    return ", ".join(f"q{q}" for q in qs)


def _ang(a):
    f = pi_multiple(a)
    if f is None:
        return f"{to_rad(a):.3f} rad"
    if f == 0:
        return "0"
    n, d = f.numerator, f.denominator
    s = "π" if abs(n) == 1 else f"{abs(n)}π"
    if d != 1:
        s += f"/{d}"
    return ("-" + s) if n < 0 else s


def _bits(v, n):
    return format(v, f"0{max(n,1)}b")


def describe(n: Node, index_of: dict | None = None) -> tuple[str, str, str]:
    """-> (code, plain, quantum-note). index_of maps op id -> 1-based step number, so references read
    as 'step 2' instead of an internal id."""
    index_of = index_of or {}
    ref_txt = lambda rid: f"step {index_of[rid]}" if rid in index_of else str(rid)
    P, T = n.params, n.targets
    op = n.op
    reps = f"  ×{n.repeat}" if n.repeat > 1 else ""
    if op == "shake":
        return (f"SHAKE [{_q(T)}]{reps}  →  spread into every possibility equally",
                "Shake puts each qubit into an even mix of 0 and 1, so all outcomes are equally likely.",
                "Hadamard on each qubit: H|0⟩ = (|0⟩+|1⟩)/√2")
    if op == "set":
        v = P.get("value", 0)
        return (f"SET [{_q(T)}] = {v}  →  load {v} (binary {_bits(v, len(T))}, q0 is the rightmost bit)",
                f"Set writes the number {v} into the register, starting from 0. The first qubit is the least-significant bit.",
                "X on every qubit whose bit is 1")
    if op == "flip":
        return (f"FLIP [{_q(T)}]{reps}  →  turn 0 into 1 and 1 into 0",
                "Flip swaps the two possibilities on each qubit, whatever state it is in.", "Pauli-X")
    if op == "phase":
        return (f"PHASE [{_q(T)}] by {_ang(P['angle'])}{reps}  →  turn the hidden angle",
                "Phase changes a hidden angle without changing any probability. You only see it after later steps mix things up.",
                f"P(θ) with θ = {_ang(P['angle'])}: |1⟩ → e^{{iθ}}|1⟩ (Z, S or T when exact)")
    if op == "rotate":
        return (f"ROTATE [{_q(T)}] around {P['axis'].upper()} by {_ang(P['angle'])}{reps}",
                "Rotate tilts the qubit by an amount you choose, so you can set exactly how likely a 1 is.",
                f"R{P['axis'].upper()}(θ), θ = {_ang(P['angle'])}; for RY, P(1) = sin²(θ/2)")
    if op == "swap":
        return (f"SWAP {_q(T)}{reps}  →  exchange the two qubits' states", "Swap trades what two qubits hold.",
                "SWAP gate (three CNOTs)")
    if op == "measure":
        return (f"MEASURE [{_q(T)}] → classical bits {n.classical}{reps}",
                "Measure looks at the qubits. Each collapses to a definite 0 or 1 and the answer is stored in a classical bit.",
                "Projective measurement in the computational basis")
    if op == "reset":
        return (f"RESET {_q(T)}  →  back to 0", "Reset forces the qubit back to 0 so it can be reused.", "Reset to |0⟩")
    if op == "control":
        b = n.body
        return (f"CONTROL on [{_q(n.controls)}]: run {b.op.upper()} [{_q(b.targets)}] only when the control is 1{reps}",
                "The step inside runs only for the part of the state where the control qubit is 1.",
                "Controlled-U: |1⟩⟨1|⊗U + |0⟩⟨0|⊗I")
    if op == "correct":
        c, b = n.condition, n.body
        return (f"CORRECT: if classical bit {c['clbit']} == {c['equals']}, run {b.op.upper()} [{_q(b.targets)}]{reps}",
                "Correct uses a measurement result to decide, while the program runs, whether to apply a fix-up step.",
                "Classically-conditioned gate (dynamic circuit)")
    if op == "entangle":
        style = P.get("style", "cx")
        return (f"ENTANGLE {_q(T)}  →  link q{T[1]} to q{T[0]}",
                "Entangle ties two qubits together: after it, their answers are correlated. It works best when the first qubit is already shaken.",
                "CNOT: Control(q%d){Flip q%d}" % (T[0], T[1]) if style == "cx" else "CZ: Control(q%d){Phase π q%d}" % (T[0], T[1]))
    if op == "encode":
        if P.get("method") == "basis":
            return (f"ENCODE [{_q(T)}] ← {P['data']}  (basis)", "Encode loads a number into the qubits as bits.", "Same as Set")
        return (f"ENCODE [{_q(T)}] ← {P['data']}  (angle, {P['scaling']})",
                "Encode turns each number into a tilt, so a qubit's chance of 1 carries the data.",
                "RY(π·x)" if P["scaling"] == "pi_x" else "RY(2·arcsin√x), so P(1) = x")
    if op == "compare":
        sym = "==" if P.get("operator", "eq") == "eq" else "!="
        return (f"COMPARE [{_q(T)}] {sym} {P['value']}  →  answer goes to q{n.ancillas[0]}",
                f"Compare checks the whole register at once and raises the flag qubit q{n.ancillas[0]} where it matches.",
                "X on zero bits · multi-controlled X onto the ancilla · undo X")
    if op == "mark":
        if P.get("via"):
            return (f"MARK via {ref_txt(P['via'])}  →  flip the hidden sign where the Compare said yes, then clean up",
                    "Mark through a Compare: tag the matching state, then undo the Compare so the flag qubit is clean again.",
                    "Compare → Phase(π) on flag → Uncompute")
        return (f"MARK [{_q(T)}] = {P['value']}  →  flip the hidden sign of that one answer",
                "Mark tags the target answer with a hidden minus sign. Probabilities don't change yet.",
                "Phase oracle: |x⟩ → (−1)^[x=value] |x⟩")
    if op == "boost":
        return (f"BOOST [{_q(T)}]{reps}  →  make the marked answer more likely",
                "Boost uses interference to move probability onto the marked answer.", "Grover diffusion: H·X·MCZ·X·H")
    if op == "fourier":
        inv = P.get("inverse", False)
        return (f"{'INVERSE ' if inv else ''}FOURIER [{_q(T)}]{reps}",
                "Fourier turns number information into hidden angles (and back, when inverse).", "Quantum Fourier transform" + (" (inverse)" if inv else ""))
    if op == "add":
        return (f"ADD {P['value']} (mod {P.get('modulus')}) to [{_q(T)}]",
                "Add changes the stored number by a fixed amount, wrapping around at the modulus, without measuring.",
                "Draper adder: QFT · phases 2π·c·2ᵏ/2ⁿ · inverse QFT")
    if op == "uncompute":
        return (f"UNCOMPUTE {ref_txt(n.ref)}  →  run it backwards", "Uncompute reverses an earlier step to clean up helper qubits.",
                "Dagger of the referenced step's gates, in reverse order")
    return (op.upper(), "", "")


def build_pseudocode(doc: Document) -> dict:
    steps = [{"n": 1, "op": "INITIALIZE", "targets": [f"q{i}" for i in range(doc.qubits)],
              "code": f"INITIALIZE [{_q(range(doc.qubits))}]  →  |{'0' * doc.qubits}⟩",
              "plain": "Every qubit starts at 0.", "qnote": f"|{'0' * doc.qubits}⟩", "id": None}]
    index_of = {n.id: i + 1 for i, n in enumerate(doc.operations)}
    for node in doc.operations:
        code, plain, qn = describe(node, index_of)
        steps.append({"n": len(steps) + 1, "op": node.op.upper(), "targets": [f"q{t}" for t in node.targets],
                      "code": code, "plain": plain, "qnote": qn, "id": node.id})
    return {"title": "Concept circuit", "meta": f"{doc.qubits} qubits · {len(doc.operations)} steps", "steps": steps,
            "summary": [], "patternNote": ""}
