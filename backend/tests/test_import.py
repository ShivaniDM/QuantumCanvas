import json

import pytest
from fastapi.testclient import TestClient

from app import app
from codeimport import ImportFailed, import_source
from concepts import compile_document
from explain.principles import principle_of
from mathlayer import analyze_document

client = TestClient(app)

SEARCH = """from qiskit import QuantumCircuit
import numpy as np

qc = QuantumCircuit(2, 2)
qc.h([0, 1])
qc.x(1)
qc.cz(0, 1)
qc.x(1)
for q in range(2):
    qc.h(q)
qc.x([0, 1])
qc.cz(0, 1)
qc.x([0, 1])
qc.h([0, 1])
qc.measure([0, 1], [0, 1])
"""


def gate(i, name, targets, controls=(), **params):
    return {"id": f"n{i}", "op": "gate", "targets": list(targets), "controls": list(controls),
            "params": {"name": name, **params}}


def doc(n, ops, clbits=0):
    return {"version": "0.4", "qubits": n, "classical_bits": clbits, "operations": ops}


def test_raw_gates_compile_to_the_same_qiskit_calls():
    res = compile_document(doc(2, [gate(1, "h", [0]), gate(2, "x", [1], [0]), gate(3, "rz", [1], angle={"pi": [1, 4]}),
                                   {"id": "m", "op": "measure", "targets": [0, 1], "classical": [0, 1]}], 2))
    assert res.ok, res.errors
    body = [l for l in res.qiskit_lines if l.startswith("qc.")]
    assert body[:3] == ["qc.h(0)", "qc.cx(0, 1)", "qc.rz(np.pi/4, 1)"]
    assert res.pseudocode["steps"][2]["code"].startswith("CX q0 → q1")


def test_raw_gates_have_an_independent_math_reference():
    d = doc(2, [gate(1, "h", [0]), gate(2, "x", [1], [0]), {"id": "m", "op": "measure", "targets": [0, 1], "classical": [0, 1]}], 2)
    log = analyze_document(d, results={"00": 500, "11": 500})
    assert log["steps"] and log["predicted"]["00"] == pytest.approx(0.5) and log["predicted"]["11"] == pytest.approx(0.5)


def test_raw_gate_validation_names_the_problem():
    res = compile_document(doc(1, [gate(1, "cx", [0])]))
    assert not res.ok and "isn't supported" in res.errors[0].message
    res = compile_document(doc(2, [gate(1, "rx", [0])]))
    assert not res.ok


def test_principle_for_a_raw_gate_follows_the_gate():
    assert principle_of("gate", gate(1, "h", [0]))["name"] == "Superposition"
    assert principle_of("gate", gate(1, "x", [1], [0]))["name"] == "Controlled operation"
    assert principle_of("gate", gate(1, "rz", [0], angle={"pi": [1, 2]}))["name"].startswith("Rotation")


def test_qiskit_import_keeps_every_gate_and_line():
    r = import_source("qiskit", SEARCH, 24)
    ops = r["document"]["operations"]
    assert r["report"]["gates"] == 14 and r["report"]["measurements"] == 2
    assert ops[0]["metadata"]["lines"] == [5] and ops[5]["metadata"]["loop"] == "q=0"
    assert all(c["ok"] for c in r["report"]["checks"])


def test_suggestions_are_offered_and_each_is_verified():
    r = import_source("qiskit", SEARCH, 24)
    titles = [s["title"] for s in r["suggestions"]]
    assert titles == ["Superposition (H) on q0, q1", "Oracle: mark |01⟩ on q0, q1", "Amplitude amplification on q0, q1"]
    assert all(s["check"]["level"] == "unitary" and s["check"]["ok"] for s in r["suggestions"])
    mark = r["suggestions"][1]
    assert mark["concept"] == {"op": "mark", "targets": [0, 1], "params": {"value": 1}} and mark["lines"] == [6, 7, 8]


def test_mismatched_flips_are_not_suggested_as_an_oracle():
    src = "qc = QuantumCircuit(2)\nqc.h([0, 1])\nqc.x(1)\nqc.cz(0, 1)\nqc.x(0)\n"
    titles = [s["title"] for s in import_source("qiskit", src, 24)["suggestions"]]
    assert not any(t.startswith("Oracle") for t in titles)


def test_unsupported_code_imports_nothing_and_names_the_line():
    with pytest.raises(ImportFailed) as e:
        import_source("qiskit", "qc = QuantumCircuit(2)\nqc.h(0)\nwhile True:\n    qc.h(0)\n", 24)
    assert e.value.unsupported[0]["line"] == 3


def test_code_is_never_executed():
    with pytest.raises(ImportFailed):
        import_source("qiskit", "qc = QuantumCircuit(1)\n__import__('os').system('echo pwned > /tmp/pwned_import')\n", 24)
    import os
    assert not os.path.exists("/tmp/pwned_import")


def test_qasm2_broadcast_and_u3_are_exact_up_to_global_phase():
    src = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[3];\ncreg c[3];\nh q;\nccx q[0],q[1],q[2];\nu3(0.3,0.2,0.1) q[0];\nmeasure q -> c;\n'
    r = import_source("qasm2", src, 24)
    assert r["report"]["checks"][1]["ok"] is True and r["report"]["notes"]


def test_qasm3_bell_suggests_superposition_and_entangle():
    src = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nbit[2] c;\nh q[0];\ncx q[0], q[1];\nc = measure q;\n'
    r = import_source("qasm3", src, 24)
    assert [s["title"] for s in r["suggestions"]] == ["Superposition (H) on q0", "Entangle (CNOT) q0 → q1"]


def test_import_endpoint_reports_failure_without_a_document():
    bad = client.post("/import", json={"format": "qasm3", "source": "OPENQASM 3.0;\nqubit[1] q;\nfoo q[0];\n"}).json()
    assert bad["ok"] is False and bad["document"] is None and bad["error"]
    good = client.post("/import", json={"format": "qiskit", "source": SEARCH}).json()
    assert good["ok"] and len(good["suggestions"]) == 3
