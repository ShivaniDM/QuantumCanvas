import json

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

import app as backend_app
import executor

client = TestClient(backend_app.app)

BELL = {"version": "0.4", "qubits": 2, "classical_bits": 2, "operations": [
    {"id": "a", "op": "shake", "targets": [0]},
    {"id": "b", "op": "entangle", "targets": [0, 1]},
    {"id": "m", "op": "measure", "targets": [0, 1], "classical": [0, 1]}]}
NO_MEASURE = {"version": "0.4", "qubits": 2, "classical_bits": 0, "operations": [
    {"id": "a", "op": "shake", "targets": [0, 1]}]}


def body(backend, doc):
    return {"canvas_json": "{}", "ir_json": json.dumps(doc), "pseudocode_txt": "", "qiskit_py": "",
            "backend": backend, "shots": 400, "concept_ir": doc}


@pytest.fixture(autouse=True)
def logs(monkeypatch, tmp_path):
    monkeypatch.setattr(backend_app.settings, "LOG_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(executor, "_store", None, raising=False)


def test_only_simulators_are_listed():
    ids = [b["id"] for b in client.get("/backends").json()["backends"]]
    assert ids[0] == "aer" and set(ids) == {"aer", "ionq_sim_ideal", "ionq_sim_forte-1", "ionq_sim_forte-enterprise-1",
                                            "ionq_sim_aria-1", "ionq_sim_aria-2"}
    labels = [b["label"] for b in client.get("/backends").json()["backends"] if b["id"].startswith("ionq")]
    assert all(l.startswith("IonQ simulator") for l in labels)


@pytest.mark.parametrize("backend", ["ibm_fez", "braket_local", "ionq_qpu_forte-1", "qpu"])
def test_hardware_and_engine_backends_are_refused(backend):
    r = client.post("/execute", json=body(backend, BELL))
    assert r.status_code == 400 and "isn't offered" in r.json()["detail"]


def test_a_circuit_without_measure_is_not_run(monkeypatch):
    import aer_runner
    monkeypatch.setattr(aer_runner, "run_aer_detailed", lambda *a, **k: pytest.fail("nothing should be run"))
    r = client.post("/execute", json=body("aer", NO_MEASURE))
    assert r.status_code == 400 and "no Measure step" in r.json()["detail"]


def test_sampling_variation_is_not_called_noise():
    log = {"predicted": {"00": 0.25, "01": 0.25, "10": 0.25, "11": 0.25},
           "checks": [{"check": "observed counts consistent with prediction", "ok": True}]}
    executor._noise_aware(log, {"00": 241, "01": 232, "10": 260, "11": 267})
    c = log["checks"][0]
    assert "normal random variation" in c["detail"] and "noise moved" not in c["detail"]


def test_real_deviation_is_reported_as_noise():
    log = {"predicted": {"00": 0.5, "11": 0.5}, "checks": [{"check": "observed counts", "ok": True}]}
    executor._noise_aware(log, {"00": 450, "11": 450, "01": 50, "10": 50})
    assert "noise moved about 10.0%" in log["checks"][0]["detail"]


def test_results_on_impossible_outcomes_are_flagged_as_a_readback_problem():
    log = {"predicted": {"00": 0.5, "11": 0.5}, "checks": [{"check": "observed counts", "ok": True}]}
    executor._noise_aware(log, {"": 1000})
    assert log["checks"][0]["ok"] is False and "reading the results back" in log["checks"][0]["detail"]


def test_ideal_simulator_counts_use_the_requested_shots(monkeypatch):
    import ionq_runner

    class Resp:
        def __init__(self, data):
            self.data, self.ok = data, True

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    runner = ionq_runner.IonQRunner("k", "https://api.example", logger=type("L", (), {"log": lambda *a: None, "save": lambda *a: None, "error": lambda *a: None})())
    job = {"id": "j", "status": "completed", "backend": "simulator", "stats": {"qubits": 2},
           "results": {"probabilities": {"url": "/v0.4/jobs/j/results/probabilities"}}}
    probs = {"0": 0.5, "3": 0.5}
    monkeypatch.setattr(runner.session, "get", lambda url, timeout=15: Resp(probs if "probabilities" in url else job))
    st = runner.get_job_status("j", shots=400)
    assert st.counts == {"00": 200, "11": 200}
