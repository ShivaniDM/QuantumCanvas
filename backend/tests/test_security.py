import json

import pytest
from fastapi.testclient import TestClient

import app as backend_app
from config import settings
from safe_qiskit import UnsafeSource, build_circuit_from_source

client = TestClient(backend_app.app)

IR_1Q = json.dumps({"version": "0.3", "qubits": 1, "classical_bits": 0, "operations": []})

LEGIT_SRC = ("from qiskit import QuantumCircuit, transpile\n"
            "from qiskit_aer import AerSimulator\n"
            "qc = QuantumCircuit(1, 1)\n"
            "qc.h(0)\n"
            "qc.measure(0, 0)\n"
            "# ── Run on Aer simulator ──────────────────────────────────────\n"
            "simulator = AerSimulator()\n")

EXPLOIT_SRC = ("import os\n"
              "os.environ['PWNED'] = '1'\n"
              "from qiskit import QuantumCircuit\n"
              "qc = QuantumCircuit(1)\n"
              "qc.h(0)\n"
              "qc.measure_all()\n")


def test_legit_generated_code_still_builds_and_runs():
    qc = build_circuit_from_source(LEGIT_SRC)
    assert qc.num_qubits == 1
    r = client.post("/execute", json={"canvas_json": "{}", "ir_json": IR_1Q, "pseudocode_txt": "",
                                      "qiskit_py": LEGIT_SRC, "backend": "aer", "shots": 50})
    assert r.status_code == 200 and sum(r.json()["counts"].values()) == 50


def test_arbitrary_python_is_refused_not_executed():
    with pytest.raises(UnsafeSource):
        build_circuit_from_source(EXPLOIT_SRC)
    r = client.post("/execute", json={"canvas_json": "{}", "ir_json": IR_1Q, "pseudocode_txt": "",
                                      "qiskit_py": EXPLOIT_SRC, "backend": "aer", "shots": 50})
    assert r.status_code == 500
    assert "PWNED" not in __import__("os").environ

    r2 = client.post("/qasm", json={"qiskit_py": EXPLOIT_SRC})
    assert r2.status_code == 400


def test_non_whitelisted_method_and_non_literal_args_are_refused():
    for bad in ("qc = QuantumCircuit(1)\nqc.save_statevector()\n",
                "qc = QuantumCircuit(1)\nqc.h(__import__('os').system(1))\n",
                "qc = QuantumCircuit(1)\nprint.h(0)\n"):
        with pytest.raises(UnsafeSource):
            build_circuit_from_source(bad)


def test_malformed_run_id_is_rejected_not_glob_matched():
    for bad in ("*", "../etc/passwd", "a" * 13, "ABCDEF012345", "a?c", ""):
        r = client.get(f"/runs/{bad}" if bad else "/runs/")
        assert r.status_code in (400, 404, 405)
        assert r.status_code != 200


def test_valid_shape_but_unknown_run_id_is_a_clean_404():
    assert client.get("/runs/000000000000").status_code == 404


def test_oversized_circuit_is_rejected_before_it_touches_the_simulator():
    big_ir = json.dumps({"version": "0.3", "qubits": settings.MAX_QUBITS + 1, "classical_bits": 0, "operations": []})
    r = client.post("/execute", json={"canvas_json": "{}", "ir_json": big_ir, "pseudocode_txt": "",
                                      "qiskit_py": "", "backend": "aer", "shots": 10})
    assert r.status_code == 400 and "qubit" in r.json()["detail"].lower()


def test_excess_shots_are_rejected():
    r = client.post("/execute", json={"canvas_json": "{}", "ir_json": IR_1Q, "pseudocode_txt": "",
                                      "qiskit_py": LEGIT_SRC, "backend": "aer", "shots": settings.MAX_SHOTS + 1})
    assert r.status_code == 400 and "shots" in r.json()["detail"].lower()


def test_oversized_document_is_rejected_at_compile_too():
    big = {"version": "0.3", "qubits": settings.MAX_QUBITS + 5, "classical_bits": 0, "operations": []}
    r = client.post("/compile", json={"document": big})
    assert r.status_code == 400


def test_qpu_backend_is_not_offered():
    r = client.post("/execute", json={"canvas_json": "{}", "ir_json": IR_1Q, "pseudocode_txt": "",
                                      "qiskit_py": LEGIT_SRC, "backend": "qpu", "shots": 10})
    assert r.status_code == 400 and "isn't offered" in r.json()["detail"]


def test_qpu_backend_is_refused_when_offered_but_not_explicitly_enabled(monkeypatch):
    from engine_bridge import bridge
    monkeypatch.setattr(bridge, "OFFERED", bridge.OFFERED + ("qpu",))
    assert str(settings.ALLOW_QPU_SUBMIT).lower() != "on"
    r = client.post("/execute", json={"canvas_json": "{}", "ir_json": IR_1Q, "pseudocode_txt": "",
                                      "qiskit_py": LEGIT_SRC, "backend": "qpu", "shots": 10})
    assert r.status_code == 403


def test_qasm_export_failure_message_names_no_internals():
    r = client.post("/qasm", json={"qiskit_py": "not even python ("})
    assert r.status_code == 400
    assert "Traceback" not in r.json()["detail"] and ".py" not in r.json()["detail"]


def test_rate_limited_reply_still_carries_cors_headers():
    from fastapi.testclient import TestClient
    import app as backend_app
    from config import settings
    before = settings.RATE_LIMIT_PER_MINUTE
    settings.RATE_LIMIT_PER_MINUTE = 1
    try:
        c = TestClient(backend_app.app)
        h = {"Origin": "http://localhost:5500"}
        body = {"format": "qiskit", "source": "x", "error": ""}
        c.post("/code-help", json=body, headers=h)
        r = c.post("/code-help", json=body, headers=h)
        assert r.status_code == 429 and r.headers.get("access-control-allow-origin")
    finally:
        settings.RATE_LIMIT_PER_MINUTE = before
