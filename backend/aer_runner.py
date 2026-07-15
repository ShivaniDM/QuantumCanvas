"""
QuantumCanvas — Aer Runner
Runs a QuantumCanvas-generated Qiskit program on the LOCAL Qiskit Aer
simulator and returns an exact measurement histogram.

The generated program is self-contained: it imports qiskit / qiskit_aer and
builds a circuit named `qc`. We execute only the circuit-construction part in
an isolated namespace, then run `qc` ourselves with the requested shot count so
the frontend's `shots` value is honoured (the generated tail hard-codes 1000).

Note: exec() runs app-generated Qiskit source. This is intended for local /
trusted use. Do not expose this endpoint to untrusted callers.
"""


class AerNotInstalled(RuntimeError):
    """Raised when qiskit / qiskit-aer is not available in the environment."""


# The generator emits this marker right before its own run/print block.
_RUN_MARKER = "# ── Run on Aer simulator"


def _strip_run_block(qiskit_code: str) -> str:
    """Drop the trailing simulate/print block so we control shots ourselves."""
    idx = qiskit_code.find(_RUN_MARKER)
    return qiskit_code[:idx] if idx != -1 else qiskit_code


def _has_measure(qc) -> bool:
    for instr in qc.data:
        if getattr(instr.operation, "name", "") == "measure":
            return True
    return False


def run_aer(qiskit_code: str, shots: int, logger=None) -> dict:
    """Execute the generated circuit on Aer and return {bitstring: count}."""
    try:
        from qiskit import QuantumCircuit, transpile
        from qiskit_aer import AerSimulator
    except Exception as e:  # ImportError, version mismatch, or backend load failure
        # Surface the real cause — a common one is an old qiskit-aer that still
        # imports ProviderV1 (removed in Qiskit 2.0). Don't mislabel it "missing".
        raise AerNotInstalled(
            f"qiskit-aer failed to import ({type(e).__name__}: {e}). "
            "Ensure compatible versions are installed: "
            "pip install -U \"qiskit>=2\" \"qiskit-aer>=0.17\""
        ) from e

    build_src = _strip_run_block(qiskit_code)
    ns: dict = {}
    exec(compile(build_src, "<quantumcanvas_qiskit>", "exec"), ns)  # noqa: S102

    qc = ns.get("qc")
    if qc is None:
        raise RuntimeError("Generated code did not define a circuit `qc`.")

    # Aer needs measurements to produce counts. If none were emitted
    # (e.g. no LOOK applied), measure the whole register into a fresh circuit.
    if not _has_measure(qc):
        nq = qc.num_qubits
        measured = QuantumCircuit(nq, nq)
        measured.compose(qc, qubits=range(nq), inplace=True)
        measured.measure(range(nq), range(nq))
        qc = measured

    sim = AerSimulator()
    compiled = transpile(qc, sim)
    result = sim.run(compiled, shots=shots).result()
    counts = result.get_counts()

    # Normalise keys: Qiskit separates classical registers with spaces.
    clean = {str(k).replace(" ", ""): int(v) for k, v in counts.items()}

    if logger:
        logger.log(
            f"Aer simulation complete — {sum(clean.values())} shots, "
            f"{len(clean)} distinct states"
        )
    return clean
