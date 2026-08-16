"""
QuantumCanvas — QASM Export
Converts a QuantumCanvas-generated Qiskit program into OpenQASM 2.0 text, for
handoff to tools like IBM Quantum Composer (paste into its code editor to get
a visual, editable circuit) independent of any direct integration.

Reuses the same "build qc without running the simulator tail" approach as
aer_runner.py, since exporting QASM only needs the constructed circuit, not
an execution.
"""

import qiskit.qasm2 as qasm2

# The generator emits this marker right before its own run/print block.
_RUN_MARKER = "# ── Run on Aer simulator"


def _strip_run_block(qiskit_code: str) -> str:
    idx = qiskit_code.find(_RUN_MARKER)
    return qiskit_code[:idx] if idx != -1 else qiskit_code


def export_qasm2(qiskit_code: str) -> str:
    """Build the circuit from generated Qiskit source and return OpenQASM 2.0 text."""
    build_src = _strip_run_block(qiskit_code)
    ns: dict = {}
    exec(compile(build_src, "<quantumcanvas_qiskit>", "exec"), ns)  # noqa: S102

    qc = ns.get("qc")
    if qc is None:
        raise RuntimeError("Generated code did not define a circuit `qc`.")

    return qasm2.dumps(qc)
