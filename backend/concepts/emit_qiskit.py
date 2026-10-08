"""L2 -> Qiskit.  One plan per gate drives BOTH the circuit and the code text,
so the code a student copies is guaranteed to build the circuit that ran."""
from __future__ import annotations

import math
from fractions import Fraction
from itertools import groupby

from .gates import Gate
from .lower import Lowered

# Import Qiskit once, at module load (the server's main thread). Importing qiskit.circuit.library for the
# first time inside a short-lived worker thread segfaulted a later thread in testing (Qiskit 2.5.2).
try:
    from qiskit import QuantumCircuit as _QuantumCircuit
    from qiskit.circuit import library as _L
except ImportError:           # the pure-Python parts (validate / lower / IonQ) still work without Qiskit
    _QuantumCircuit = _L = None

RUN_MARKER = "# ── Run on Aer simulator"   # same marker the legacy generator uses

_CLASS = {"x": "XGate", "y": "YGate", "z": "ZGate", "h": "HGate", "s": "SGate", "sdg": "SdgGate",
          "t": "TGate", "tdg": "TdgGate", "p": "PhaseGate", "rx": "RXGate", "ry": "RYGate",
          "rz": "RZGate", "swap": "SwapGate"}
_PLAIN_1Q = ("x", "y", "z", "h", "s", "sdg", "t", "tdg")


def fmt_angle(th: float) -> str:
    """np.pi style when th is a small rational multiple of pi, else a float literal."""
    x = th / math.pi
    f = Fraction(x).limit_denominator(64)
    if abs(float(f) - x) < 1e-12:
        if f == 0:
            return "0"
        n, d = f.numerator, f.denominator
        s = "np.pi" if abs(n) == 1 else f"{abs(n)}*np.pi"
        if d != 1:
            s += f"/{d}"
        return ("-" + s) if n < 0 else s
    return repr(float(th))


def _plan(g: Gate):
    """-> ("call", method, args)  |  ("append", ClassName, params, nctl, qubits)"""
    c, t, p = list(g.controls), list(g.targets), list(g.params)
    if g.name == "measure":
        return ("call", "measure", [t[0], g.clbits[0]])
    if g.name == "reset":
        return ("call", "reset", [t[0]])
    if not c:
        if g.name in _PLAIN_1Q:
            return ("call", g.name, [t[0]])
        if g.name in ("p", "rx", "ry", "rz"):
            return ("call", g.name, [("angle", p[0]), t[0]])
        if g.name == "swap":
            return ("call", "swap", [t[0], t[1]])
    else:
        k = len(c)
        if g.name == "x":
            if k == 1: return ("call", "cx", [c[0], t[0]])
            if k == 2: return ("call", "ccx", [c[0], c[1], t[0]])
            return ("call", "mcx", [("list", c), t[0]])
        if g.name == "z" and k == 1:
            return ("call", "cz", [c[0], t[0]])
        if g.name == "p":
            if k == 1: return ("call", "cp", [("angle", p[0]), c[0], t[0]])
            return ("call", "mcp", [("angle", p[0]), ("list", c), t[0]])
        if g.name in ("rx", "ry", "rz") and k == 1:
            return ("call", "c" + g.name, [("angle", p[0]), c[0], t[0]])
        if g.name == "swap" and k == 1:
            return ("call", "cswap", [c[0], t[0], t[1]])
        if g.name in ("h", "y") and k == 1:
            return ("call", "c" + g.name, [c[0], t[0]])
    return ("append", _CLASS[g.name], p, len(c), c + t)


def _arg_code(a):
    if isinstance(a, tuple):
        kind, v = a
        return fmt_angle(v) if kind == "angle" else "[" + ", ".join(str(x) for x in v) + "]"
    return str(a)


def _plan_code(plan) -> str:
    if plan[0] == "call":
        return f"qc.{plan[1]}({', '.join(_arg_code(a) for a in plan[2])})"
    _, cls, params, k, qs = plan
    ps = ", ".join(fmt_angle(x) for x in params)
    gate = f"{cls}({ps})" + (f".control({k})" if k else "")
    return f"qc.append({gate}, [{', '.join(str(q) for q in qs)}])"


def _need_qiskit():
    if _QuantumCircuit is None:
        raise RuntimeError("Qiskit is not installed: pip install \"qiskit>=2\"")


def _plan_apply(qc, plan):
    L = _L
    if plan[0] == "call":
        args = [a[1] if isinstance(a, tuple) else a for a in plan[2]]
        getattr(qc, plan[1])(*args)
    else:
        _, cls, params, k, qs = plan
        gate = getattr(L, cls)(*params)
        qc.append(gate.control(k) if k else gate, qs)


def _cond_blocks(gates):
    """Group consecutive gates sharing the same condition -> [(cond, [(index, gate)])]."""
    out = []
    for cond, grp in groupby(enumerate(gates), key=lambda ig: ig[1].cond):
        out.append((cond, list(grp)))
    return out


def build_circuit(low: Lowered):
    _need_qiskit()
    QuantumCircuit = _QuantumCircuit
    qc = QuantumCircuit(low.qubits, low.clbits) if low.clbits else QuantumCircuit(low.qubits)
    for cond, grp in _cond_blocks(low.gates):
        if cond is None:
            for _, g in grp:
                _plan_apply(qc, _plan(g))
        else:
            with qc.if_test((qc.clbits[cond[0]], cond[1])):
                for _, g in grp:
                    _plan_apply(qc, _plan(g))
    return qc


def to_code(low: Lowered, node_labels: dict | None = None, with_tail: bool = True):
    """-> (lines, line_gates).  line_gates[i] = gate indices the i-th line produced."""
    node_labels = node_labels or {}
    body_lines: list[tuple[str, list]] = []
    plans = [_plan(g) for g in low.gates]
    # one header per top-level step, in order, even for a step that lowers to zero gates:
    # the math layer pairs code blocks with IR steps one-to-one.
    for top, idxs in low.node_ranges.items():
        body_lines.append((f"# {node_labels.get(top, top)}", []))
        for cond, grp in _cond_blocks([low.gates[i] for i in idxs]):
            indent = ""
            if cond is not None:
                body_lines.append((f"with qc.if_test((qc.clbits[{cond[0]}], {cond[1]})):", []))
                indent = "    "
            for k, _ in grp:
                i = idxs[k]
                body_lines.append((indent + _plan_code(plans[i]), [i]))

    imports = sorted({p[1] for p in plans if p[0] == "append"})
    lines: list[tuple[str, list]] = [("from qiskit import QuantumCircuit", []), ("import numpy as np", [])]
    if imports:
        lines.append((f"from qiskit.circuit.library import {', '.join(imports)}", []))
    lines += [("", []),
              (f"qc = QuantumCircuit({low.qubits}, {low.clbits})" if low.clbits else f"qc = QuantumCircuit({low.qubits})", []),
              ("", [])]
    lines += body_lines
    if with_tail:
        has_measure = any(g.name == "measure" for g in low.gates)
        lines += [("", []), (f"{RUN_MARKER} ──────────────────────────────────────────", [])]
        if not has_measure:
            lines.append(("qc.measure_all()  # no Measure step, so measure every qubit", []))
        lines += [("from qiskit_aer import AerSimulator", []), ("from qiskit import transpile", []),
                  ("simulator = AerSimulator()", []),
                  ("counts = simulator.run(transpile(qc, simulator), shots=1000).result().get_counts()", []),
                  ('print(qc.draw(output="text"))', []),
                  ("for state, count in sorted(counts.items(), key=lambda x: -x[1]):", []),
                  ('    print(f"  |{state}>: {count} ({count/10:.1f}%)")', [])]
    return [l for l, _ in lines], [g for _, g in lines]


def to_qasm3(low: Lowered) -> str:
    _need_qiskit()
    from qiskit import qasm3
    return qasm3.dumps(build_circuit(low))
