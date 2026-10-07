"""
QuantumCanvas — Aer Runner
Runs a QuantumCanvas-generated Qiskit program on the LOCAL Qiskit Aer
simulator and returns an exact measurement histogram.

The generated program is self-contained: it imports qiskit / qiskit_aer and
builds a circuit named `qc`. We build only the circuit-construction part via
safe_qiskit's AST-only parser (never exec()), then run `qc` ourselves with the
requested shot count so the frontend's `shots` value is honoured (the generated
tail hard-codes 1000).

Security: this used to exec() the request body as Python, which is remote code
execution for anyone who can reach the API. It now never executes the text —
see safe_qiskit.py for the whitelist this is built from.
"""

from safe_qiskit import UnsafeSource, build_circuit_from_source, strip_run_block as _strip_run_block


class AerNotInstalled(RuntimeError):
    """Raised when qiskit / qiskit-aer is not available in the environment."""


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

    try:
        qc = build_circuit_from_source(qiskit_code)
    except UnsafeSource as e:
        raise RuntimeError(f"Generated code could not be built safely: {e}") from e

    return _simulate(qc, shots, logger)


def run_aer_circuit(qc, shots: int, logger=None, seed: int | None = None) -> dict:
    """Run an already-built Qiskit circuit (the concept compiler's output) on Aer.

    No exec() here: the circuit is built from the compiled gate list, not from source text.
    """
    try:
        from qiskit_aer import AerSimulator  # noqa: F401
    except Exception as e:
        raise AerNotInstalled(f"qiskit-aer failed to import ({type(e).__name__}: {e}).") from e
    return _simulate(qc, shots, logger, seed)


def _simulate(qc, shots: int, logger=None, seed: int | None = None) -> dict:
    return run_aer_detailed(qc, shots, logger=logger, seed=seed)["counts"]


def run_aer_detailed(qc, shots: int, logger=None, seed: int | None = None) -> dict:
    """Run on Aer and return EVERYTHING needed to audit the run: counts, the backend that executed (from Aer's own
    result), the seed, the transpiled circuit, timings and the full raw result."""
    import json
    import random
    import time
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator

    # Aer needs measurements to produce counts. If none were emitted
    # (e.g. no LOOK applied), measure the whole register into a fresh circuit.
    if not _has_measure(qc):
        nq = qc.num_qubits
        if qc.num_clbits <= nq:
            measured = QuantumCircuit(nq, nq)
            measured.compose(qc, qubits=range(nq), clbits=range(qc.num_clbits), inplace=True)
            measured.measure(range(nq), range(nq))
        else:                       # more classical bits than qubits: add a separate register
            measured = qc.copy()
            measured.measure_all()
        qc = measured

    seed = random.SystemRandom().randrange(2 ** 31) if seed is None else int(seed)
    sim = AerSimulator()
    t0 = time.perf_counter()
    compiled = transpile(qc, sim, seed_transpiler=seed)
    t1 = time.perf_counter()
    result = sim.run(compiled, shots=shots, seed_simulator=seed).result()
    t2 = time.perf_counter()
    counts = result.get_counts()

    # Normalise keys: Qiskit separates classical registers with spaces.
    clean = {str(k).replace(" ", ""): int(v) for k, v in counts.items()}

    try:
        from qiskit import qasm3
        text, fmt = qasm3.dumps(compiled), "openqasm3"
    except Exception:
        text, fmt = str(compiled.draw(output="text")), "text-drawing"
    ops = {k: int(v) for k, v in compiled.count_ops().items()}
    two_q = sum(v for k, v in ops.items() if k in ("cx", "cz", "swap", "ecr", "cp", "crx", "cry", "crz", "ccx"))
    try:
        raw = json.loads(json.dumps(result.to_dict(), default=str))
    except Exception as e:                                         # keep the failure visible, never drop silently
        raw = {"unserialisable_result": str(e)}
    details = {
        "counts": clean,
        "backend_name": getattr(result, "backend_name", None) or (raw.get("backend_name") if isinstance(raw, dict) else None),
        "seed": seed, "shots": shots, "raw": raw,
        "transpiled": {"format": fmt, "circuit": text, "depth": compiled.depth(), "size": compiled.size(),
                       "count_ops": ops, "two_qubit_gates": int(two_q), "num_qubits": compiled.num_qubits,
                       "basis_gates": sorted(sim.configuration().basis_gates)},
        "timing": {"transpile_ms": round((t1 - t0) * 1000, 2), "execute_ms": round((t2 - t1) * 1000, 2),
                   "provider_time_taken_s": raw.get("time_taken") if isinstance(raw, dict) else None},
    }
    if logger:
        logger.log(
            f"Aer simulation complete — {sum(clean.values())} shots, "
            f"{len(clean)} distinct states, seed={seed}"
        )
    return details
