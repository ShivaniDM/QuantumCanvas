import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from concepts import compile_document
from concepts.emit_qiskit import build_circuit
from config import settings


@pytest.fixture(autouse=True)
def _no_rate_limit():
    before = settings.RATE_LIMIT_PER_MINUTE, settings.RATE_LIMIT_LIGHT_PER_MINUTE
    settings.RATE_LIMIT_PER_MINUTE = settings.RATE_LIMIT_LIGHT_PER_MINUTE = 0
    yield
    settings.RATE_LIMIT_PER_MINUTE, settings.RATE_LIMIT_LIGHT_PER_MINUTE = before


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
    d = sv.probabilities_dict()
    k = max(d, key=d.get)
    return k, d[k]
