from __future__ import annotations

import re

PRINCIPLES = {
    "set": ("Basis encoding", "basis",
            "A number is stored by writing its binary digits into qubits that start at 0."),
    "flip": ("Bit flip (Pauli X)", "flip",
             "X swaps the amplitudes of 0 and 1, the quantum version of a classical NOT."),
    "encode": ("State preparation", "prepar",
               "Rotations set the amplitudes so that measurement probabilities match the data."),
    "reset": ("Measurement and reset", "reset",
              "Measuring a qubit and then forcing it back to 0 lets it be reused."),
    "shake": ("Superposition", "superposition",
              "A Hadamard gives a qubit equal amplitudes for 0 and 1, so both outcomes stay possible until measured."),
    "rotate": ("Rotation on the Bloch sphere", "rotat",
               "Turning the state by an angle sets how likely 1 is; from 0, a Y rotation by θ gives P(1) = sin²(θ/2)."),
    "phase": ("Relative phase", "phase",
              "A phase turns the |1⟩ amplitude without changing probabilities on its own; it matters once amplitudes interfere."),
    "entangle": ("Entanglement", "entangle",
                 "A controlled gate acting on a superposition links qubits, so their outcomes are correlated and can't be described one qubit at a time."),
    "swap": ("State exchange (SWAP)", "swap",
             "SWAP exchanges the complete states of two qubits, including any entanglement they carry."),
    "control": ("Controlled operation", "control",
                "The gate acts only on the part of the state where every control qubit is 1."),
    "compare": ("Reversible oracle", "oracle",
                "A reversible circuit flags the inputs that match a condition on a helper qubit without destroying the input."),
    "mark": ("Phase oracle (phase kickback)", "phase",
             "Flipping the sign of the target state's amplitude marks it; probabilities stay the same until interference turns the sign into a difference."),
    "boost": ("Amplitude amplification (interference)", "interfer",
              "Reflecting every amplitude about the average makes marked states' amplitudes grow and the others shrink."),
    "uncompute": ("Uncomputation", "uncomput",
                  "Running a computation backwards returns helper qubits to 0 so they stop being entangled with the answer."),
    "fourier": ("Quantum Fourier transform", "fourier",
                "Turns a number stored in basis states into phases, the core of phase estimation and period finding."),
    "add": ("Reversible arithmetic", "reversib",
            "Adds a fixed number modulo 2^n with reversible gates, so no information is lost."),
    "measure": ("Measurement (Born rule)", "measure",
                "Each outcome appears with probability equal to its squared amplitude, and the state collapses to that outcome."),
    "correct": ("Classical feed-forward", "feed-forward",
                "A later gate depends on an earlier measurement result, as in the corrections of quantum teleportation."),
}


GATE_PRINCIPLE = {"h": "shake", "x": "flip", "y": "flip", "z": "phase", "s": "phase", "sdg": "phase", "t": "phase",
                  "tdg": "phase", "p": "phase", "rx": "rotate", "ry": "rotate", "rz": "rotate", "swap": "swap"}


def principle_key(op: str, node: dict | None = None) -> str:
    if op != "gate" or not node:
        return op
    if node.get("controls"):
        return "control"
    return GATE_PRINCIPLE.get((node.get("params") or {}).get("name"), op)


def principle_of(op: str, node: dict | None = None) -> dict | None:
    row = PRINCIPLES.get(principle_key(op, node))
    if row is None:
        return None
    name, keyword, idea = row
    return {"name": name, "keyword": keyword, "idea": idea}


def names_principle(text: str, op: str, node: dict | None = None) -> bool:
    row = PRINCIPLES.get(principle_key(op, node))
    return row is None or re.search(re.escape(row[1]), text or "", re.I) is not None


def code_blocks(qiskit_py: str, step_ids: list[str]) -> dict:
    lines = (qiskit_py or "").split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("qc = QuantumCircuit")) + 1
    except StopIteration:
        return {}
    blocks, current = [], None
    for line in lines[start:]:
        if line.startswith("# ── Run on"):
            break
        if line.startswith("# "):
            current = []
            blocks.append(current)
        elif current is not None and line.strip():
            current.append(line.rstrip())
    return {sid: "\n".join(b) for sid, b in zip(step_ids, blocks)}
