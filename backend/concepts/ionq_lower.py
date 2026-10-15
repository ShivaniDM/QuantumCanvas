from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .gates import Gate, add_controls
from .lower import Lowered


class BackendUnsupported(Exception):
    pass


@dataclass
class IonQResult:
    circuit: dict
    src_index: list
    rewritten: bool


def defer_measurements(low: Lowered):
    out: list[Gate] = []
    src: list[int] = []
    deferred: list[tuple[Gate, int]] = []
    pending: dict[int, int] = {}
    measured_q: set[int] = set()
    rewritten = False

    for i, g in enumerate(low.gates):
        if g.name == "measure":
            q, c = g.targets[0], g.clbits[0]
            if q in measured_q:
                raise BackendUnsupported(
                    f"Qubit q{q} is measured twice. IonQ can't reuse a qubit after measuring it, "
                    f"so this circuit can only run on the Aer simulator.")
            pending[c] = q
            measured_q.add(q)
            deferred.append((g, i))
            continue
        if g.name == "reset":
            raise BackendUnsupported(
                f"Reset on q{g.targets[0]} needs mid-circuit control that IonQ doesn't offer here. "
                f"Run this circuit on the Aer simulator instead.")
        if g.cond is not None:
            clbit, val = g.cond
            if clbit not in pending:
                raise BackendUnsupported("A classically controlled step reads a classical bit that was never measured.")
            qa = pending[clbit]
            if qa in set(g.targets) | set(g.controls):
                raise BackendUnsupported(
                    f"The classically controlled step on q{qa} acts on the qubit it was measured from; IonQ can't do that.")
            base = replace(g, cond=None)
            rewritten = True
            if val == 1:
                for g2 in add_controls(base, (qa,)):
                    out.append(g2); src.append(i)
            else:
                out.append(Gate("x", (qa,))); src.append(i)
                for g2 in add_controls(base, (qa,)):
                    out.append(g2); src.append(i)
                out.append(Gate("x", (qa,))); src.append(i)
            continue
        bad = [q for q in g.qubits() if q in measured_q]
        if bad:
            raise BackendUnsupported(
                f"q{bad[0]} is used again after it was measured. IonQ measures only at the end, "
                f"so this circuit can only run on the Aer simulator.")
        out.append(g); src.append(i)

    for g, i in deferred:
        out.append(g); src.append(i)
    return out, src, rewritten


_PLAIN = {"x": "x", "y": "y", "z": "z", "h": "h", "s": "s", "sdg": "si", "t": "t", "tdg": "ti"}
_ROT = ("rx", "ry", "rz")


def _cnot(c, t):
    return {"gate": "cnot", "control": c, "target": t}


def _lower_gate(g: Gate) -> list[dict]:
    c, t, p = list(g.controls), list(g.targets), list(g.params)
    if g.name == "measure":
        return []
    if not c:
        if g.name in _PLAIN:
            return [{"gate": _PLAIN[g.name], "target": t[0]}]
        if g.name in _ROT:
            return [{"gate": g.name, "target": t[0], "rotation": p[0]}]
        if g.name == "p":
            return [{"gate": "rz", "target": t[0], "rotation": p[0]}]
        if g.name == "swap":
            a, b = t
            return [_cnot(a, b), _cnot(b, a), _cnot(a, b)]
    k = len(c)
    if g.name == "x":
        if k == 1:
            return [_cnot(c[0], t[0])]
        return [{"gate": "mcx", "target": t[0], "controls": c}]
    if g.name == "z" and k == 1:
        return [{"gate": "h", "target": t[0]}, _cnot(c[0], t[0]), {"gate": "h", "target": t[0]}]
    if g.name == "h" and k == 1:
        return [{"gate": "ry", "target": t[0], "rotation": math.pi / 4}, _cnot(c[0], t[0]),
                {"gate": "ry", "target": t[0], "rotation": -math.pi / 4}]
    if g.name == "p" and k == 1:
        th = p[0]
        return [{"gate": "rz", "target": c[0], "rotation": th / 2},
                {"gate": "rz", "target": t[0], "rotation": th / 2},
                _cnot(c[0], t[0]), {"gate": "rz", "target": t[0], "rotation": -th / 2}, _cnot(c[0], t[0])]
    if g.name in ("ry", "rz") and k == 1:
        th = p[0]
        return [{"gate": g.name, "target": t[0], "rotation": th / 2}, _cnot(c[0], t[0]),
                {"gate": g.name, "target": t[0], "rotation": -th / 2}, _cnot(c[0], t[0])]
    if g.name == "rx" and k == 1:
        th = p[0]
        return ([{"gate": "h", "target": t[0]}] + _lower_gate(Gate("rz", g.targets, g.controls, g.params))
                + [{"gate": "h", "target": t[0]}])
    if g.name == "swap" and k == 1:
        a, b = t
        return [_cnot(b, a), {"gate": "mcx", "target": b, "controls": [c[0], a]}, _cnot(b, a)]
    raise BackendUnsupported(
        f"IonQ can't run a {k}-controlled {g.name.upper()} directly. "
        f"Run this circuit on the Aer simulator instead.")


def lower_for_ionq(low: Lowered) -> IonQResult:
    gates, src, rewritten = defer_measurements(low)
    out, srcs = [], []
    for g, i in zip(gates, src):
        for d in _lower_gate(g):
            out.append(d); srcs.append(i)
    return IonQResult({"gateset": "qis", "qubits": low.qubits, "circuit": out}, srcs, rewritten)


def rewritten_lowered(low: Lowered) -> Lowered:
    gates, src, _ = defer_measurements(low)
    return Lowered(gates, [low.trace[i] for i in src], low.qubits, low.clbits, {})
