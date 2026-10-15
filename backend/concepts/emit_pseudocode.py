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


_GATE_PLAIN = {
    "h": "Hadamard: maps |0⟩ to (|0⟩+|1⟩)/√2 and |1⟩ to (|0⟩−|1⟩)/√2.",
    "x": "Pauli-X: swaps the amplitudes of |0⟩ and |1⟩ (a bit flip).",
    "y": "Pauli-Y: a bit flip combined with a phase flip.",
    "z": "Pauli-Z: flips the sign of the |1⟩ amplitude; probabilities don't change.",
    "s": "S: turns the phase of |1⟩ by π/2.",
    "sdg": "S†: turns the phase of |1⟩ by −π/2.",
    "t": "T: turns the phase of |1⟩ by π/4.",
    "tdg": "T†: turns the phase of |1⟩ by −π/4.",
    "p": "Phase gate: turns the phase of |1⟩ by the given angle.",
    "rx": "Rotation about the X axis of the Bloch sphere.",
    "ry": "Rotation about the Y axis of the Bloch sphere.",
    "rz": "Rotation about the Z axis of the Bloch sphere.",
    "swap": "SWAP: exchanges the states of two qubits.",
}
_GATE_NOTE = {"h": "H = (1/√2)[[1, 1], [1, −1]]", "x": "X = [[0, 1], [1, 0]]", "y": "Y = [[0, −i], [i, 0]]",
              "z": "Z = [[1, 0], [0, −1]]", "s": "S = diag(1, i)", "sdg": "S† = diag(1, −i)", "t": "T = diag(1, e^{iπ/4})",
              "tdg": "T† = diag(1, e^{−iπ/4})", "p": "P(θ) = diag(1, e^{iθ})", "rx": "RX(θ) = exp(−iθX/2)",
              "ry": "RY(θ) = exp(−iθY/2)", "rz": "RZ(θ) = exp(−iθZ/2)", "swap": "SWAP|a b⟩ = |b a⟩"}


def describe(n: Node, index_of: dict | None = None) -> tuple[str, str, str]:
    index_of = index_of or {}
    ref_txt = lambda rid: f"step {index_of[rid]}" if rid in index_of else str(rid)
    P, T = n.params, n.targets
    op = n.op
    reps = f"  ×{n.repeat}" if n.repeat > 1 else ""
    if op == "shake":
        return (f"SUPERPOSE [{_q(T)}]{reps}  →  Hadamard on each qubit: equal superposition",
                "Superposition (H) gives each qubit equal amplitudes for 0 and 1, so both outcomes are equally likely when measured.",
                "Hadamard on each qubit: H|0⟩ = (|0⟩+|1⟩)/√2")
    if op == "gate":
        name = P.get("name", "?")
        g = name.upper() + (f"({_ang(P['angle'])})" if "angle" in P else "")
        if n.controls:
            g = "C" * len(n.controls) + g
            return (f"{g} {_q(n.controls)} → {_q(T)}{reps}",
                    f"Gate {g}: applies {name.upper()} to {_q(T)} only where {_q(n.controls)} {'is' if len(n.controls) == 1 else 'are all'} 1.",
                    f"Controlled-{name.upper()}")
        return (f"{g} [{_q(T)}]{reps}", _GATE_PLAIN.get(name, f"Gate {g}."), _GATE_NOTE.get(name, g))
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
        return (f"IF c{c['clbit']} == {c['equals']}: run {b.op.upper()} [{_q(b.targets)}]{reps}  (classically controlled)",
                "A classically controlled step uses a measurement result, while the circuit runs, to decide whether to apply the step inside (feed-forward).",
                "Classically-conditioned gate (dynamic circuit)")
    if op == "entangle":
        style = P.get("style", "cx")
        return (f"ENTANGLE {_q(T)}  →  link q{T[1]} to q{T[0]}",
                "Entangle ties two qubits together: after it, their answers are correlated. It creates entanglement only when the control qubit is in superposition.",
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
            return (f"ORACLE via {ref_txt(P['via'])}  →  flip the sign where the Compare said yes, then clean up",
                    "The oracle marks the matching states through a Compare, then undoes the Compare so the flag qubit is clean again.",
                    "Compare → Phase(π) on flag → Uncompute")
        return (f"ORACLE [{_q(T)}] marks |{_bits(P['value'], len(T))}⟩  →  flip the sign of that one basis state",
                f"The oracle marks the basis state |{_bits(P['value'], len(T))}⟩ (read right to left: q{T[0] if T else 0} is the rightmost bit) "
                "with a minus sign on its amplitude. Probabilities don't change yet.",
                "Phase oracle: |x⟩ → (−1)^[x=value] |x⟩")
    if op == "boost":
        return (f"AMPLIFY [{_q(T)}]{reps}  →  amplitude amplification toward the marked state",
                "Amplitude amplification reflects every amplitude about the average, so interference moves probability onto the marked state.",
                "Grover diffusion: H·X·MCZ·X·H")
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
