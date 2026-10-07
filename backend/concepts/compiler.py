"""Compile pipeline: parse -> validate -> expand+lower -> emit."""
from __future__ import annotations

from dataclasses import dataclass, field

from .emit_pseudocode import build_pseudocode, describe
from .emit_qiskit import build_circuit, to_code, to_qasm3
from .ionq_lower import BackendUnsupported, lower_for_ionq
from .lower import Lowered, lower_document
from .schema import Document, SchemaError, parse_document, to_dict
from .validate import Issue, Report, validate


@dataclass
class CompileResult:
    ok: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    document: dict | None = None
    lowered: Lowered | None = None
    gates: list = field(default_factory=list)
    trace: list = field(default_factory=list)
    node_ranges: dict = field(default_factory=dict)
    qiskit_lines: list = field(default_factory=list)
    line_gates: list = field(default_factory=list)
    qiskit_py: str = ""
    qasm3: str | None = None
    step_log: dict | None = None
    pseudocode: dict | None = None
    ionq: dict | None = None
    ionq_src: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "document": self.document,
            "gates": self.gates,
            "trace": [list(t) for t in self.trace],
            "node_ranges": self.node_ranges,
            "qiskit_lines": self.qiskit_lines,
            "line_gates": self.line_gates,
            "qiskit_py": self.qiskit_py,
            "qasm3": self.qasm3,
            "step_log": self.step_log,
            "pseudocode": self.pseudocode,
            "ionq": self.ionq,
            "ionq_src": self.ionq_src,
        }


COMPILE_MAX_QUBITS = 12          # the live /compile path stays snappy; post-run analysis uses the full limit
COMPILE_MAX_COUNTERFACTUAL_STEPS = 24


def _apply_math_log(res, doc, index_of):
    """Render the pseudocode's per-step facts from the math layer's step log (never from templates alone)."""
    try:
        from mathlayer import analyze_document
        from explain.template import UNMEASURED_WARNING, idle_steps, render_step
        ir = res.document
        log = analyze_document(ir, max_qubits=COMPILE_MAX_QUBITS, code_check=False,
                               counterfactual=len(ir["operations"]) <= COMPILE_MAX_COUNTERFACTUAL_STEPS)
    except Exception:                                  # the math layer must never break compilation
        return
    res.step_log = log
    by_id = {n["id"]: n for n in ir["operations"]}
    steps = {s["id"]: s for s in log.get("steps", [])}
    for st in res.pseudocode["steps"]:
        sid = st.get("id")
        if sid not in steps:
            continue
        r = render_step(steps[sid], by_id[sid])
        if r["plain"]:
            st["plain"] = r["plain"]
        if r["effect"]:
            st["effect"] = r["effect"]
            st["plain"] = (st["plain"] + " Result: " + r["effect"]).strip()
        if r["claim_ok"] is not None:
            st["claim_ok"] = r["claim_ok"]
    for oid in idle_steps(log):
        res.warnings.append(Issue("W_UNMEASURED_EFFECT", "warning", UNMEASURED_WARNING, oid,
                                  "Measure the qubits this step works on, or remove the step."))


def compile_document(raw: dict, *, backend: str | None = None, with_qasm: bool = False) -> CompileResult:
    """Deterministic: the same Concept IR always yields the same output.

    backend="ionq" additionally lowers for IonQ; if the circuit needs something IonQ lacks,
    a W_BACKEND_UNSUPPORTED warning is added and ``ionq`` stays None (callers must refuse the submit).
    """
    try:
        doc: Document = parse_document(raw)
    except SchemaError as e:
        return CompileResult(False, [Issue("E_SCHEMA", "error", str(e))])

    rep: Report = validate(doc)
    res = CompileResult(rep.ok, rep.errors, rep.warnings, document=to_dict(doc))
    if not rep.ok:
        return res

    low = lower_document(doc)
    index_of = {n.id: i + 1 for i, n in enumerate(doc.operations)}
    # Code comments name the action only. The "→ what it does" clause is a template claim, and a comment in
    # copy-pasted code must never assert something the circuit may not do (see concepts/analysis.py).
    labels = {n.id: describe(n, index_of)[0].split("  →")[0] for n in doc.operations}
    lines, line_gates = to_code(low, labels)
    res.lowered = low
    res.gates = [g.to_dict() for g in low.gates]
    res.trace = low.trace
    res.node_ranges = low.node_ranges
    res.qiskit_lines, res.line_gates = lines, line_gates
    res.qiskit_py = "\n".join(lines)
    res.pseudocode = build_pseudocode(doc)
    _apply_math_log(res, doc, index_of)
    if with_qasm:
        res.qasm3 = to_qasm3(low)
    if backend == "ionq":
        try:
            r = lower_for_ionq(low)
            res.ionq, res.ionq_src = r.circuit, r.src_index
        except BackendUnsupported as e:
            res.warnings.append(Issue("W_BACKEND_UNSUPPORTED", "warning", str(e), None,
                                      "Run it on the Aer simulator, or change the circuit."))
    return res
