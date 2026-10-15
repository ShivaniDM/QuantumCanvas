import importlib

from safe_qiskit import UnsafeSource, build_circuit_from_source


class AerNotInstalled(RuntimeError):
    pass


def _has_measure(qc) -> bool:
    for instr in qc.data:
        if getattr(instr.operation, "name", "") == "measure":
            return True
    return False


def run_aer(qiskit_code: str, shots: int, logger=None) -> dict:
    try:
        importlib.import_module("qiskit")
        importlib.import_module("qiskit_aer")
    except Exception as e:
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
    try:
        importlib.import_module("qiskit_aer")
    except Exception as e:
        raise AerNotInstalled(f"qiskit-aer failed to import ({type(e).__name__}: {e}).") from e
    return _simulate(qc, shots, logger, seed)


def _simulate(qc, shots: int, logger=None, seed: int | None = None) -> dict:
    return run_aer_detailed(qc, shots, logger=logger, seed=seed)["counts"]


def run_aer_detailed(qc, shots: int, logger=None, seed: int | None = None) -> dict:
    import json
    import random
    import time
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator

    if not _has_measure(qc):
        nq = qc.num_qubits
        if qc.num_clbits <= nq:
            measured = QuantumCircuit(nq, nq)
            measured.compose(qc, qubits=range(nq), clbits=range(qc.num_clbits), inplace=True)
            measured.measure(range(nq), range(nq))
        else:
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
    except Exception as e:
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
