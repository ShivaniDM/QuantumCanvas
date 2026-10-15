from __future__ import annotations

import math
import re
from fractions import Fraction

from .qiskit_subset import SUPPORTED_SUMMARY, SubsetError, parse as parse_qiskit
from .lifting import suggest

FORMATS = ("qasm3", "qasm2", "qiskit")
MAX_SOURCE_CHARS = 200_000
EXACT_CHECK_MAX_QUBITS = 10

_PLAIN = {"h", "x", "y", "z", "s", "sdg", "t", "tdg"}
_ROT = {"p", "rx", "ry", "rz"}
_CTRL = {"cx": ("x", 1), "cy": ("y", 1), "cz": ("z", 1), "ch": ("h", 1), "cp": ("p", 1), "crx": ("rx", 1),
         "cry": ("ry", 1), "crz": ("rz", 1), "ccx": ("x", 2), "cswap": ("swap", 1), "cu1": ("p", 1)}
_ALIAS = {"u1": "p", "cnot": "cx", "toffoli": "ccx", "phase": "p", "cphase": "cp", "fredkin": "cswap"}
_SKIP = {"barrier", "id", "delay"}


class ImportFailed(ValueError):
    def __init__(self, message: str, unsupported: list | None = None):
        super().__init__(message)
        self.unsupported = unsupported or []


def _angle(theta: float) -> dict:
    f = Fraction(theta / math.pi).limit_denominator(64)
    if abs(float(f) * math.pi - theta) < 1e-10 and f != 0:
        return {"pi": [f.numerator, f.denominator]}
    return {"rad": float(theta)}


def _qasm_statement_lines(source: str) -> list[int]:
    out, depth = [], 0
    skip = re.compile(r"^(OPENQASM|include|qreg|creg|qubit|bit|gate|opaque|input|output|const|def|barrier)\b")
    for i, raw in enumerate(source.splitlines(), start=1):
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if depth == 0 and not skip.match(line) and line.endswith(";"):
            out.append(i)
        depth += line.count("{") - line.count("}")
    return out


def _load(fmt: str, source: str):
    if fmt == "qiskit":
        try:
            return parse_qiskit(source)
        except SubsetError as e:
            raise ImportFailed(f"Line {e.line}: {e}" if e.line else str(e),
                               [{"line": e.line, "construct": e.construct or "", "message": str(e),
                                 "supported": SUPPORTED_SUMMARY}]) from e
    try:
        if fmt == "qasm3":
            from qiskit import qasm3
            qc = qasm3.loads(source)
        else:
            from qiskit import qasm2
            qc = qasm2.loads(source, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
    except Exception as e:
        msg = str(e).strip().splitlines()[0][:400] if str(e).strip() else type(e).__name__
        m = re.search(r"line (\d+)", str(e))
        raise ImportFailed(f"This isn't valid {'OpenQASM 3' if fmt == 'qasm3' else 'OpenQASM 2'}: {msg}",
                           [{"line": int(m.group(1)) if m else None, "construct": "syntax", "message": msg}]) from e
    stmt_lines = _qasm_statement_lines(source)
    real = [ins for ins in qc.data if ins.operation.name not in _SKIP]
    prov = [{"line": ln} for ln in stmt_lines] if len(stmt_lines) == len(real) else [{} for _ in real]
    it = iter(prov)
    return qc, [next(it) if ins.operation.name not in _SKIP else {} for ins in qc.data]


def _node(ix: int, op: str, **kw) -> dict:
    return {"id": f"g{ix}", "op": op, "targets": kw.get("targets", []), "controls": kw.get("controls", []),
            "ancillas": [], "classical": kw.get("classical", []), "params": kw.get("params", {}),
            "condition": None, "body": None, "ref": None, "repeat": 1, "metadata": kw.get("metadata", {})}


def _convert(qc, prov) -> tuple[list[dict], list[dict], list[str]]:
    nodes, unsupported, notes = [], [], []
    idx = lambda q: qc.find_bit(q).index
    for k, ins in enumerate(qc.data):
        op = ins.operation
        name = _ALIAS.get(op.name, op.name)
        qs = [idx(q) for q in ins.qubits]
        meta = {"source": "import", **({"lines": [prov[k]["line"]]} if prov[k].get("line") else {}),
                **({"loop": prov[k]["loop"]} if prov[k].get("loop") else {})}
        line = prov[k].get("line")
        if getattr(op, "condition", None) is not None or op.name in ("if_else", "while_loop", "for_loop", "switch_case"):
            unsupported.append({"line": line, "construct": op.name, "message": "classically controlled operations aren't imported yet"})
            continue
        params = [float(p) for p in op.params] if op.params else []
        if name in _SKIP:
            continue
        if name == "measure":
            nodes.append(_node(len(nodes), "measure", targets=qs, classical=[idx(c) for c in ins.clbits], metadata=meta))
        elif name == "reset":
            nodes.append(_node(len(nodes), "reset", targets=qs, metadata=meta))
        elif name in _PLAIN:
            nodes.append(_node(len(nodes), "gate", targets=qs, params={"name": name}, metadata=meta))
        elif name in _ROT:
            nodes.append(_node(len(nodes), "gate", targets=qs, params={"name": name, "angle": _angle(params[0])}, metadata=meta))
        elif name == "swap":
            nodes.append(_node(len(nodes), "gate", targets=qs, params={"name": "swap"}, metadata=meta))
        elif name in _CTRL:
            base, k_ctrl = _CTRL[name]
            p = {"name": base, **({"angle": _angle(params[0])} if base in _ROT else {})}
            nodes.append(_node(len(nodes), "gate", targets=qs[k_ctrl:], controls=qs[:k_ctrl], params=p, metadata=meta))
        elif name == "mcx":
            nodes.append(_node(len(nodes), "gate", targets=qs[-1:], controls=qs[:-1], params={"name": "x"}, metadata=meta))
        elif name == "sx":
            nodes.append(_node(len(nodes), "gate", targets=qs, params={"name": "rx", "angle": {"pi": [1, 2]}}, metadata=meta))
            notes.append("SX was imported as RX(π/2); they differ only by a global phase, which no measurement can see.")
        elif name in ("u", "u3", "u2"):
            th, ph, la = (params if name != "u2" else [math.pi / 2] + params)
            for g, a in (("rz", la), ("ry", th), ("rz", ph)):
                if abs(a) > 1e-12:
                    nodes.append(_node(len(nodes), "gate", targets=qs, params={"name": g, "angle": _angle(a)}, metadata=meta))
            notes.append("U(θ, φ, λ) was imported as RZ(λ) · RY(θ) · RZ(φ); they differ only by a global phase.")
        else:
            unsupported.append({"line": line, "construct": op.name,
                                "message": f"the gate '{op.name}' isn't supported yet"})
    merged: list[dict] = []
    for n in nodes:
        prev = merged[-1] if merged else None
        if prev and n["op"] == prev["op"] == "measure" and not set(n["targets"]) & set(prev["targets"]):
            prev["targets"] += n["targets"]; prev["classical"] += n["classical"]
            lines = sorted(set(prev["metadata"].get("lines", []) + n["metadata"].get("lines", [])))
            if lines:
                prev["metadata"]["lines"] = lines
        else:
            merged.append(n)
    for i, n in enumerate(merged):
        n["id"] = f"g{i + 1}"
    return merged, unsupported, sorted(set(notes))


def _strip_final_measurements(qc):
    from qiskit import QuantumCircuit
    out = QuantumCircuit(qc.num_qubits)
    for ins in qc.data:
        if ins.operation.name in ("measure", "barrier", "id", "delay"):
            continue
        if ins.operation.name == "reset":
            return None
        out.append(ins.operation, [qc.find_bit(q).index for q in ins.qubits])
    return out


def _checks(qc, document, compiled) -> list[dict]:
    from qiskit.quantum_info import Operator
    from concepts.emit_qiskit import build_circuit
    checks = []
    src_ops = {k: v for k, v in qc.count_ops().items() if k not in _SKIP}
    n_measure = src_ops.get("measure", 0)
    got_measure = sum(len(n["targets"]) for n in document["operations"] if n["op"] == "measure")
    checks.append({"check": "every measurement kept, with its classical bit", "ok": n_measure == got_measure,
                   "detail": f"{n_measure} in the code, {got_measure} imported"})
    mid = any(n["op"] in ("reset",) for n in document["operations"])
    measured_at = {}
    for i, n in enumerate(document["operations"]):
        for t in n["targets"] + n["controls"]:
            if n["op"] != "measure" and t in measured_at:
                mid = True
        if n["op"] == "measure":
            for t in n["targets"]:
                measured_at[t] = i
    if qc.num_qubits > EXACT_CHECK_MAX_QUBITS or mid:
        checks.append({"check": "same operation as the code (unitary, up to global phase)", "ok": None,
                       "detail": "not checked: " + ("the circuit measures or resets a qubit and then uses it again"
                                                    if mid else f"more than {EXACT_CHECK_MAX_QUBITS} qubits")})
        return checks
    a = _strip_final_measurements(qc)
    b = _strip_final_measurements(build_circuit(compiled.lowered))
    same = a is not None and b is not None and Operator(a).equiv(Operator(b))
    checks.append({"check": "same operation as the code (unitary, up to global phase)", "ok": bool(same),
                   "detail": f"compared as {qc.num_qubits}-qubit operators within numerical tolerance"})
    return checks


def import_source(fmt: str, source: str, max_qubits: int) -> dict:
    if fmt not in FORMATS:
        raise ImportFailed(f"Unknown format {fmt!r}: use one of {', '.join(FORMATS)}.")
    if not isinstance(source, str) or not source.strip():
        raise ImportFailed("Paste some code first.")
    if len(source) > MAX_SOURCE_CHARS:
        raise ImportFailed(f"The code is longer than {MAX_SOURCE_CHARS} characters.")
    qc, prov = _load(fmt, source)
    if qc.num_qubits > max_qubits:
        raise ImportFailed(f"This circuit has {qc.num_qubits} qubits; the limit here is {max_qubits}.")
    if qc.num_qubits == 0:
        raise ImportFailed("The circuit has no qubits.")
    nodes, unsupported, notes = _convert(qc, prov)
    if unsupported:
        raise ImportFailed(f"{len(unsupported)} line{'s' if len(unsupported) != 1 else ''} couldn't be imported, "
                           "so nothing was imported. Nothing is dropped silently.", unsupported)
    document = {"version": "0.4", "qubits": qc.num_qubits, "classical_bits": qc.num_clbits, "operations": nodes}
    from concepts import compile_document
    compiled = compile_document(document)
    if not compiled.ok:
        raise ImportFailed("The imported circuit didn't pass validation: " + "; ".join(e.message for e in compiled.errors))
    gate_count = sum(1 for n in nodes if n["op"] == "gate")
    report = {"format": fmt, "qubits": qc.num_qubits, "classical_bits": qc.num_clbits, "gates": gate_count,
              "measurements": sum(len(n["targets"]) for n in nodes if n["op"] == "measure"),
              "line_numbers": any(n["metadata"].get("lines") for n in nodes),
              "loops": sorted({n["metadata"]["loop"].split("=")[0] for n in nodes if n["metadata"].get("loop")}),
              "notes": notes, "unsupported": [], "checks": _checks(qc, document, compiled)}
    return {"ok": True, "document": document, "report": report,
            "suggestions": suggest(nodes, qc.num_qubits) if qc.num_qubits <= EXACT_CHECK_MAX_QUBITS else []}
