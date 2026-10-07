"""Logical Gate IR (L2): backend-neutral gates.

Names: x y z h s sdg t tdg p rx ry rz swap measure reset.
Any gate can carry ``controls``; the emitters pick cx / ccx / mcx / cz / cp /
mcp / cry ... from the number of controls. ``cond`` = (clbit, value) means
"only run when that classical bit equals value" (a Correct).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

ONE_QUBIT = ("x", "y", "z", "h", "s", "sdg", "t", "tdg", "p", "rx", "ry", "rz")
PARAMETRIC = ("p", "rx", "ry", "rz")
SELF_INVERSE = ("x", "y", "z", "h", "swap")
INVERSE_NAME = {"s": "sdg", "sdg": "s", "t": "tdg", "tdg": "t"}
NON_UNITARY = ("measure", "reset")

# Phase gates that become p(theta) as soon as a control is attached.
PHASE_AS_P = {"z": math.pi, "s": math.pi / 2, "t": math.pi / 4,
              "sdg": -math.pi / 2, "tdg": -math.pi / 4}


class LoweringError(ValueError):
    pass


@dataclass(frozen=True)
class Gate:
    name: str
    targets: tuple = ()
    controls: tuple = ()
    params: tuple = ()
    clbits: tuple = ()
    cond: tuple | None = None   # (clbit, value)

    def qubits(self):
        return tuple(self.controls) + tuple(self.targets)

    def to_dict(self) -> dict:
        d = {"name": self.name, "targets": list(self.targets)}
        if self.controls:
            d["controls"] = list(self.controls)
        if self.params:
            d["params"] = [float(p) for p in self.params]
        if self.clbits:
            d["clbits"] = list(self.clbits)
        if self.cond is not None:
            d["cond"] = {"clbit": self.cond[0], "equals": self.cond[1]}
        return d


def inverse(g: Gate) -> Gate:
    if g.name in NON_UNITARY or g.cond is not None:
        raise LoweringError(f"'{g.name}' cannot be undone")
    if g.name in SELF_INVERSE:
        return g
    if g.name in INVERSE_NAME:
        return replace(g, name=INVERSE_NAME[g.name])
    if g.name in PARAMETRIC:
        return replace(g, params=tuple(-p for p in g.params))
    raise LoweringError(f"no inverse known for gate '{g.name}'")


def is_pi(x: float) -> bool:
    return math.isclose(x, math.pi, abs_tol=1e-12) or math.isclose(x, -math.pi, abs_tol=1e-12)


def normalise_controlled(g: Gate) -> list[Gate]:
    """Canonical form of a (possibly controlled) gate.

    * controlled Z / P(pi): 1 control -> CZ; 2+ controls -> H . MCX . H
    * controlled S/T/Sdg/Tdg -> P(theta) with controls (never RZ)
    """
    if not g.controls:
        return [g]
    if g.name in PHASE_AS_P and g.name != "z":
        g = replace(g, name="p", params=(PHASE_AS_P[g.name],))
    is_cz = g.name == "z" or (g.name == "p" and is_pi(g.params[0]))
    if is_cz:
        if len(g.controls) == 1:
            return [Gate("z", g.targets, g.controls)]
        t = g.targets[0]
        return [Gate("h", (t,)), Gate("x", (t,), g.controls), Gate("h", (t,))]
    return [g]


def add_controls(g: Gate, controls) -> list[Gate]:
    if g.name in NON_UNITARY or g.cond is not None:
        raise LoweringError("Control cannot wrap a Measure, Reset or Correct")
    return normalise_controlled(replace(g, controls=tuple(controls) + tuple(g.controls)))


def mcz(controls, target) -> list[Gate]:
    """Phase flip on |1..1> of controls+target."""
    return normalise_controlled(Gate("z", (target,), tuple(controls)))
