import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from concepts import compile_document          # noqa: E402
from concepts.emit_qiskit import build_circuit  # noqa: E402
from config import settings                     # noqa: E402


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """The in-memory per-IP rate limit (ratelimit.py) is a production safety net against one
    client exhausting a single server instance — tests intentionally fire many requests in a
    row through the same TestClient, so it's disabled here rather than tripped by test speed."""
    before = settings.RATE_LIMIT_PER_MINUTE
    settings.RATE_LIMIT_PER_MINUTE = 0
    yield
    settings.RATE_LIMIT_PER_MINUTE = before


def make_doc(n, ops, c=0):
    return {"version": "0.3", "qubits": n, "classical_bits": c, "operations": ops}


def node(i, op, targets=None, **kw):
    d = {"id": f"op_{i}", "op": op, "targets": list(targets or [])}
    d.update(kw)
    return d


def compiled(n, ops, c=0, **kw):
    res = compile_document(make_doc(n, ops, c), **kw)
    assert res.ok, [e.message for e in res.errors]
    return res


def circuit_of(n, ops, c=0):
    return build_circuit(compiled(n, ops, c).lowered)


def operator_of(n, ops, c=0):
    """Unitary of the circuit, ignoring final measurements."""
    from qiskit.quantum_info import Operator
    qc = circuit_of(n, ops, c).remove_final_measurements(inplace=False)
    return Operator(qc)


def state_of(n, ops, c=0):
    from qiskit.quantum_info import Statevector
    return Statevector(circuit_of(n, ops, c).remove_final_measurements(inplace=False))


def codes(res):
    return [e.code for e in res.errors]


def warn_codes(res):
    return [w.code for w in res.warnings]


def top_prob(sv):
    """Most likely basis label and its probability (the dict has ~1e-37 dust entries)."""
    d = sv.probabilities_dict()
    k = max(d, key=d.get)
    return k, d[k]
