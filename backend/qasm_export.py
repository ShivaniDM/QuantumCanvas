"""
QuantumCanvas — QASM Export
Converts a QuantumCanvas-generated Qiskit program into OpenQASM 2.0 text, for
handoff to tools like IBM Quantum Composer (paste into its code editor to get
a visual, editable circuit) independent of any direct integration.

Builds the circuit via safe_qiskit's AST-only parser (never exec()) — see that
module for the security reasoning.
"""

import qiskit.qasm2 as qasm2

from safe_qiskit import UnsafeSource, build_circuit_from_source


def export_qasm2(qiskit_code: str) -> str:
    """Build the circuit from generated Qiskit source and return OpenQASM 2.0 text."""
    try:
        qc = build_circuit_from_source(qiskit_code)
    except UnsafeSource as e:
        raise RuntimeError(f"Generated code could not be built safely: {e}") from e
    return qasm2.dumps(qc)
