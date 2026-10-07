"""Expand composites and lower to the Logical Gate IR (L2), keeping a trace.

trace[i] is the chain of op ids that produced gate i, innermost first:
    ["op_9.0", "op_9"]   # a synthetic child of composite op_9
The LAST element is always the top-level node the user placed on the canvas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from fractions import Fraction

from .angles import pi_multiple, to_rad
from .gates import (Gate, LoweringError, add_controls, inverse, mcz,
                    normalise_controlled)
from .schema import Document, Node

# exact phase names, keyed by the angle as a multiple of pi, reduced mod 2
_EXACT_PHASE = {Fraction(1): "z", Fraction(1, 2): "s", Fraction(1, 4): "t",
                Fraction(3, 2): "sdg", Fraction(7, 4): "tdg"}


@dataclass
class Lowered:
    gates: list
    trace: list            # list[tuple[str, ...]]
    qubits: int
    clbits: int
    node_ranges: dict      # top-level op id -> list of gate indices


def _synth(parent: Node, suffix: str, op: str, **kw) -> Node:
    return Node(id=f"{parent.id}.{suffix}", op=op, **kw)


class Lowerer:
    def __init__(self, doc: Document):
        self.doc = doc
        self.by_id: dict[str, Node] = {}
        stack = list(doc.operations)
        while stack:
            n = stack.pop()
            self.by_id[n.id] = n
            if n.body is not None:
                stack.append(n.body)

    # ── public ────────────────────────────────────────────────────────
    def run(self) -> Lowered:
        gates, trace, ranges = [], [], {}
        for node in self.doc.operations:
            start = len(gates)
            for g, chain in self.lower(node):
                gates.append(g)
                trace.append(chain)
            ranges[node.id] = list(range(start, len(gates)))
        return Lowered(gates, trace, self.doc.qubits, self.doc.classical_bits, ranges)

    # ── dispatch ──────────────────────────────────────────────────────
    def lower(self, node: Node):
        once = self._lower_once(node)
        return once * max(1, node.repeat) if node.repeat > 1 else once

    def _lower_once(self, node: Node):
        fn = getattr(self, f"_op_{node.op}", None)
        if fn is None:
            raise LoweringError(f"unknown concept '{node.op}'")
        return fn(node)

    def _own(self, node, gates):
        return [(g, (node.id,)) for g in gates]

    def _wrap(self, node, children):
        """Lower synthetic child nodes and tag every gate with this node as parent."""
        out = []
        for c in children:
            out += [(g, ch + (node.id,)) for g, ch in self.lower(c)]
        return out

    # ── primitives ────────────────────────────────────────────────────
    def _op_shake(self, n):
        return self._own(n, [Gate("h", (t,)) for t in n.targets])

    def _op_set(self, n):
        v = n.params["value"]
        return self._own(n, [Gate("x", (t,)) for i, t in enumerate(n.targets) if (v >> i) & 1])

    def _op_flip(self, n):
        return self._own(n, [Gate("x", (t,)) for t in n.targets])

    def _op_phase(self, n):
        a = n.params["angle"]
        f = pi_multiple(a)
        gates = []
        for t in n.targets:
            if f is not None and f % 2 == 0:
                continue                                     # a full turn is the identity
            if f is not None and (f % 2) in _EXACT_PHASE:
                gates.append(Gate(_EXACT_PHASE[f % 2], (t,)))
            else:
                gates.append(Gate("p", (t,), params=(to_rad(a),)))   # never RZ
        return self._own(n, gates)

    def _op_rotate(self, n):
        th = to_rad(n.params["angle"])
        return self._own(n, [Gate("r" + n.params["axis"], (t,), params=(th,)) for t in n.targets])

    def _op_swap(self, n):
        return self._own(n, [Gate("swap", tuple(n.targets))])

    def _op_measure(self, n):
        return self._own(n, [Gate("measure", (t,), clbits=(c,)) for t, c in zip(n.targets, n.classical)])

    def _op_reset(self, n):
        return self._own(n, [Gate("reset", (n.targets[0],))])

    # ── modifiers ─────────────────────────────────────────────────────
    def _op_control(self, n):
        out = []
        for g, ch in self.lower(n.body):
            for g2 in add_controls(g, n.controls):
                out.append((g2, ch + (n.id,)))
        return out

    def _op_correct(self, n):
        c = n.condition
        out = []
        for g, ch in self.lower(n.body):
            if g.name in ("measure", "reset") or g.cond is not None:
                raise LoweringError("Correct cannot wrap a Measure, Reset or another Correct")
            out.append((replace(g, cond=(c["clbit"], c["equals"])), ch + (n.id,)))
        return out

    # ── composites ────────────────────────────────────────────────────
    def _op_entangle(self, n):
        t0, t1 = n.targets
        if n.params.get("style", "cx") == "cz":
            body = _synth(n, "b", "phase", targets=[t1], params={"angle": {"pi": [1, 1]}})
        else:
            body = _synth(n, "b", "flip", targets=[t1])
        return self._wrap(n, [_synth(n, "0", "control", controls=[t0], body=body)])

    def _op_encode(self, n):
        P = n.params
        if P["method"] == "basis":
            return self._wrap(n, [_synth(n, "0", "set", targets=list(n.targets), params={"value": P["data"]})])
        kids = []
        for i, (t, x) in enumerate(zip(n.targets, P["data"])):
            th = math.pi * x if P["scaling"] == "pi_x" else 2 * math.asin(math.sqrt(x))
            kids.append(_synth(n, str(i), "rotate", targets=[t], params={"axis": "y", "angle": {"rad": th}}))
        return self._wrap(n, kids)

    def _x_on_zero_bits(self, targets, value):
        return [Gate("x", (t,)) for i, t in enumerate(targets) if not (value >> i) & 1]

    def _op_compare(self, n):
        T, anc, v = n.targets, n.ancillas[0], n.params["value"]
        flips = self._x_on_zero_bits(T, v)
        gates = list(flips) + [Gate("x", (anc,), tuple(T))] + list(flips)
        if n.params.get("operator", "eq") == "neq":
            gates.append(Gate("x", (anc,)))
        return self._own(n, gates)

    def _op_mark(self, n):
        P = n.params
        if P.get("via"):
            ref = self.by_id[P["via"]]
            kids = [_synth(n, "p", "phase", targets=list(ref.ancillas), params={"angle": {"pi": [1, 1]}}),
                    _synth(n, "u", "uncompute", ref=ref.id)]
            return self._wrap(n, kids)
        T = n.targets
        flips = self._x_on_zero_bits(T, P["value"])
        gates = list(flips) + mcz(T[:-1], T[-1]) + list(flips)
        return self._own(n, gates)

    def _op_boost(self, n):
        T = n.targets
        h = [Gate("h", (t,)) for t in T]
        x = [Gate("x", (t,)) for t in T]
        return self._own(n, h + x + mcz(T[:-1], T[-1]) + x + h)

    def _qft_gates(self, T, swaps=True):
        gs = []
        for j in reversed(range(len(T))):
            gs.append(Gate("h", (T[j],)))
            for k in reversed(range(j)):
                gs += normalise_controlled(Gate("p", (T[j],), (T[k],), (math.pi / 2 ** (j - k),)))
        if swaps:
            gs += [Gate("swap", (T[i], T[len(T) - 1 - i])) for i in range(len(T) // 2)]
        return gs

    def _op_fourier(self, n):
        gs = self._qft_gates(n.targets, n.params.get("swaps", True))
        if n.params.get("inverse", False):
            gs = [inverse(g) for g in reversed(gs)]
        return self._own(n, gs)

    def _op_add(self, n):
        T, N = n.targets, len(n.targets)
        c = n.params["value"] % (1 << N)
        qft = self._qft_gates(T, True)
        mid = []
        for k, t in enumerate(T):
            th = 2 * math.pi * c * (2 ** k) / (2 ** N)
            f = Fraction(c * 2 ** k, 2 ** N) % 1
            if f != 0:
                mid.append(Gate("p", (t,), params=(th,)))
        return self._own(n, qft + mid + [inverse(g) for g in reversed(qft)])

    def _op_uncompute(self, n):
        ref = self.by_id[n.ref]
        items = self.lower(ref)
        out = []
        for g, ch in reversed(items):
            out.append((inverse(g), ch + (n.id,)))
        return out


def lower_document(doc: Document) -> Lowered:
    return Lowerer(doc).run()
