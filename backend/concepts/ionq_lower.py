"""L2 -> IonQ native-ish "qis" circuit, plus the deferred-measurement rewrite.

IonQ (per plan section 6) has no classical feed-forward, so a Correct

    measure q_a -> c ;  correct(c == 1){ U on q_t }

is rewritten into  control(q_a){ U on q_t }  with the measurement moved to the
end. That is only valid while q_a is not used again between its measurement and
the end of the circuit; otherwise we refuse with a plain-language reason.

Gate shapes follow ionq_runner.py: {"gate", "target"|"control"+"target"|"controls"}.
Rotation gates use "rotation" (radians). NOTE: IonQ's docs were not reachable when
this was written; re-check "rotation" and the mcx name against the current API docs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .gates import Gate, LoweringError, add_controls, normalise_controlled
from .lower import Lowered


class BackendUnsupported(Exception):
    """Raised with a learner-readable reason; compile turns it into W_BACKEND_UNSUPPORTED."""


@dataclass
class IonQResult:
    circuit: dict          # {"gateset": "qis", "qubits": n, "circuit": [...]}
    src_index: list        # for every IonQ gate, the L2 gate index it came from
    rewritten: bool        # True if a deferred-measurement rewrite was applied


# ── deferred measurement ────────────────────────────────────────────────
def defer_measurements(low: Lowered):
    """Return (gates, source_indices, rewritten). Raises BackendUnsupported."""
    out: list[Gate] = []
    src: list[int] = []
    deferred: list[tuple[Gate, int]] = []      # measures moved to the end
    pending: dict[int, int] = {}               # clbit -> qubit it was measured from
    measured_q: set[int] = set()               # qubits already measured (quantum role ends here)
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
                raise BackendUnsupported("A Correct reads a classical bit that was never measured.")
            qa = pending[clbit]
            if qa in set(g.targets) | set(g.controls):
                raise BackendUnsupported(
                    f"The Correct on q{qa} acts on the qubit it was measured from; IonQ can't do that.")
            base = replace(g, cond=None)
            rewritten = True
            if val == 1:
                for g2 in add_controls(base, (qa,)):
                    out.append(g2); src.append(i)
            else:   # condition on 0: flip the control qubit around the controlled gate
                out.append(Gate("x", (qa,))); src.append(i)
                for g2 in add_controls(base, (qa,)):
                    out.append(g2); src.append(i)
                out.append(Gate("x", (qa,))); src.append(i)
            continue
        # an ordinary gate: it may not touch an already-measured qubit
        bad = [q for q in g.qubits() if q in measured_q]
        if bad:
            raise BackendUnsupported(
                f"q{bad[0]} is used again after it was measured. IonQ measures only at the end, "
                f"so this circuit can only run on the Aer simulator.")
        out.append(g); src.append(i)

    for g, i in deferred:
        out.append(g); src.append(i)
    return out, src, rewritten


# ── gate by gate ────────────────────────────────────────────────────────
_PLAIN = {"x": "x", "y": "y", "z": "z", "h": "h", "s": "s", "sdg": "si", "t": "t", "tdg": "ti"}
_ROT = ("rx", "ry", "rz")


def _cnot(c, t):
    return {"gate": "cnot", "control": c, "target": t}


def _lower_gate(g: Gate) -> list[dict]:
    c, t, p = list(g.controls), list(g.targets), list(g.params)
    if g.name == "measure":
        return []                                   # implicit: IonQ measures everything at the end
    if not c:
        if g.name in _PLAIN:
            return [{"gate": _PLAIN[g.name], "target": t[0]}]
        if g.name in _ROT:
            return [{"gate": g.name, "target": t[0], "rotation": p[0]}]
        if g.name == "p":                           # global phase is unobservable without a control
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
    if g.name == "h" and k == 1:        # CH = RY(pi/4) . CX . RY(-pi/4) on the target
        return [{"gate": "ry", "target": t[0], "rotation": math.pi / 4}, _cnot(c[0], t[0]),
                {"gate": "ry", "target": t[0], "rotation": -math.pi / 4}]
    if g.name == "p" and k == 1:        # CP(th) = P(th/2) on control . CX . P(-th/2) on target . CX . P(th/2) on target
        th = p[0]
        return [{"gate": "rz", "target": c[0], "rotation": th / 2},
                {"gate": "rz", "target": t[0], "rotation": th / 2},
                _cnot(c[0], t[0]), {"gate": "rz", "target": t[0], "rotation": -th / 2}, _cnot(c[0], t[0])]
    if g.name in ("ry", "rz") and k == 1:   # CR(th) = R(th/2) . CX . R(-th/2) . CX  (X anticommutes with Y and Z)
        th = p[0]
        return [{"gate": g.name, "target": t[0], "rotation": th / 2}, _cnot(c[0], t[0]),
                {"gate": g.name, "target": t[0], "rotation": -th / 2}, _cnot(c[0], t[0])]
    if g.name == "rx" and k == 1:           # X commutes with RX, so conjugate a CRZ by H: RX = H . RZ . H
        th = p[0]
        return ([{"gate": "h", "target": t[0]}] + _lower_gate(Gate("rz", g.targets, g.controls, g.params))
                + [{"gate": "h", "target": t[0]}])
    if g.name == "swap" and k == 1:     # Fredkin = CX(b,a) . Toffoli(c,a,b) . CX(b,a)
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
    """The L2 circuit after the deferred-measurement rewrite (used by tests and the how-view)."""
    gates, src, _ = defer_measurements(low)
    return Lowered(gates, [low.trace[i] for i in src], low.qubits, low.clbits, {})
