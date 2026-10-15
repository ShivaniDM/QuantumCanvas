import qiskit.qasm2 as qasm2

from safe_qiskit import UnsafeSource, build_circuit_from_source


def export_qasm2(qiskit_code: str) -> str:
    try:
        qc = build_circuit_from_source(qiskit_code)
    except UnsafeSource as e:
        raise RuntimeError(f"Generated code could not be built safely: {e}") from e
    return qasm2.dumps(qc)
