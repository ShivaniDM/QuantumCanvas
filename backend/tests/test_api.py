"""HTTP surface: /compile, /problems, /check-problem and the concept path of /execute (Aer)."""
import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import app as backend_app  # noqa: E402
from conftest import make_doc, node  # noqa: E402

client = TestClient(backend_app.app)
BELL = make_doc(2, [node(1, "shake", [0]), node(2, "entangle", [0, 1]),
                    node(3, "measure", [0, 1], classical=[0, 1])], 2)


def test_compile_document():
    r = client.post("/compile", json={"document": BELL, "backend": "ionq", "qasm": True}).json()
    assert r["ok"] and r["gates"] and r["qiskit_py"] and r["ionq"] and "OPENQASM 3" in r["qasm3"]
    assert r["pseudocode"]["steps"][1]["op"] == "SHAKE" and len(r["trace"]) == len(r["gates"])


def test_compile_reports_errors_without_raising():
    bad = make_doc(1, [node(1, "flip", [3])])
    r = client.post("/compile", json={"document": bad}).json()
    assert not r["ok"] and r["errors"][0]["code"] == "E_QUBIT_RANGE"


def test_compile_merges_legacy_ir_and_new_nodes():
    legacy = {"qubits": [{"id": "q1", "taggedOps": [{"op": "shake", "seq": 0}]},
                         {"id": "q2", "taggedOps": []}], "edges": []}
    r = client.post("/compile", json={"legacy_ir": legacy, "nodes": [
        {"id": "N1", "op": "entangle", "targets": [0, 1], "seq": 1}]}).json()
    assert r["ok"] and [o["op"] for o in r["document"]["operations"]] == ["shake", "entangle"]


def test_problems_and_check():
    ps = client.get("/problems").json()
    assert len(ps) == 14 and all("reference_solution" not in p for p in ps)
    import problems
    ref = problems.get_problem("p_same")["reference_solution"]
    ok = client.post("/check-problem", json={"problem_id": "p_same", "document": ref}).json()
    assert ok["passed"]
    assert client.post("/check-problem", json={"problem_id": "nope", "document": ref}).status_code == 404


def test_execute_concept_ir_on_aer(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app.settings, "LOG_DIR", str(tmp_path), raising=False)
    body = {"canvas_json": "{}", "ir_json": "{\"k\":1}", "pseudocode_txt": "", "qiskit_py": "# archived only",
            "backend": "aer", "shots": 500, "concept_ir": BELL}
    r = client.post("/execute", json=body)
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert set(counts) <= {"00", "11"} and sum(counts.values()) == 500


def test_execute_invalid_concept_ir_is_a_400_with_plain_message(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app.settings, "LOG_DIR", str(tmp_path), raising=False)
    body = {"canvas_json": "{}", "ir_json": "{\"k\":2}", "pseudocode_txt": "", "qiskit_py": "",
            "backend": "aer", "shots": 10, "concept_ir": make_doc(1, [node(1, "flip", [4])])}
    r = client.post("/execute", json=body)
    assert r.status_code == 400 and "qubit" in r.json()["detail"]


def test_execute_ionq_refuses_what_ionq_cannot_run(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app.settings, "LOG_DIR", str(tmp_path), raising=False)
    doc = make_doc(1, [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]), node(3, "reset", [0])], 1)
    body = {"canvas_json": "{}", "ir_json": "{\"k\":3}", "pseudocode_txt": "", "qiskit_py": "",
            "backend": "ionq", "shots": 10, "concept_ir": doc}
    r = client.post("/execute", json=body)
    assert r.status_code == 400 and "Aer" in r.json()["detail"]


def test_legacy_execute_path_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app.settings, "LOG_DIR", str(tmp_path), raising=False)
    code = "from qiskit import QuantumCircuit\nqc = QuantumCircuit(1,1)\nqc.x(0)\nqc.measure(0,0)\n"
    body = {"canvas_json": "{}", "ir_json": "{\"k\":4}", "pseudocode_txt": "", "qiskit_py": code, "backend": "aer", "shots": 50}
    r = client.post("/execute", json=body)
    assert r.status_code == 200 and r.json()["counts"] == {"1": 50}
