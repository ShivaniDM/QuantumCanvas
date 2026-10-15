import json

import pytest
from fastapi.testclient import TestClient

import app as backend_app
from conftest import make_doc, node
from engine_bridge import client as engine_client
from engine_bridge.bridge import remap_qubit_counts
from test_composites import teleport_doc

client = TestClient(backend_app.app)
BELL = make_doc(2, [node(1, "shake", [0]), node(2, "entangle", [0, 1]),
                    node(3, "measure", [0, 1], classical=[0, 1])], 2)
RESET = make_doc(2, [node(1, "flip", [0]), node(2, "measure", [0], classical=[0]),
                     node(3, "reset", [0]), node(4, "shake", [1])], 1)


def _body(backend, doc=BELL, **kw):
    return {"canvas_json": "{}", "ir_json": json.dumps(doc), "pseudocode_txt": "", "qiskit_py": "",
            "backend": backend, "shots": 300, "concept_ir": doc, **kw}


@pytest.fixture()
def engine_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(backend_app.settings, "LOG_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(backend_app.settings, "ENGINE_URL", "http://engine.test", raising=False)
    monkeypatch.setattr(backend_app.settings, "ENGINE_API_KEY", "qce_00000000_" + "s" * 30, raising=False)
    yield
    engine_client.use_transport(None)


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class StubEngine:
    LISTING = {"groups": {}, "backends": [
        {"id": "aer", "label": "Built-in simulator", "group": "local_sim", "provider": "aer", "kind": "ideal",
         "qubits": 24, "aliases": ["builtin"], "unavailable": None},
        {"id": "ibm_fez", "label": "IBM Fez", "group": "local_sim", "provider": "ibm", "kind": "noise_model",
         "qubits": 156, "device": "FakeFez", "family": "Heron r2", "aliases": [], "unavailable": None},
        {"id": "ionq_qpu_forte-1", "label": "IonQ Forte 1 (quantum computer)", "group": "hardware",
         "provider": "ionq", "kind": "hardware", "qubits": 36, "device": "qpu.forte-1", "aliases": ["qpu"],
         "unavailable": None}]}

    def __init__(self, tamper=False, down=False):
        self.tamper, self.down, self.headers = tamper, down, []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.headers.append(headers or {})
        if self.down:
            raise ConnectionError("refused")
        if url.endswith("/v1/backends"):
            return _Resp(200, self.LISTING)
        if url.endswith("/v1/compile"):
            from qiskit import qasm3
            qc = qasm3.loads(json["circuit"]["source"])
            ops = {k: int(v) for k, v in sorted(qc.count_ops().items())}
            if self.tamper:
                ops = {**ops, "x": ops.get("x", 0) + 1}
            return _Resp(200, {"ok": True, "blocking": [], "checks": [], "changes": [], "measure_map": {},
                               "n_clbits": qc.num_clbits, "backend": {"id": json["backend"]},
                               "received": {"num_qubits": qc.num_qubits, "num_clbits": qc.num_clbits,
                                            "count_ops": ops}})
        return _Resp(404, {"detail": "not here"})


def test_without_an_engine_builtin_and_ionq_still_work(tmp_path, monkeypatch):
    import ionq_runner
    monkeypatch.setattr(backend_app.settings, "LOG_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(backend_app.settings, "ENGINE_URL", "", raising=False)
    monkeypatch.setattr(backend_app.settings, "IONQ_API_KEY", "test-key", raising=False)
    r = client.get("/backends").json()
    by = {b["id"]: b for b in r["backends"]}
    assert r["engine"]["ok"] is False and by["aer"]["unavailable"] is None
    assert by["ionq_sim_aria-1"]["unavailable"] is None and "compile engine" in by["ibm_fez"]["unavailable"]
    assert client.post("/transpile", json={"concept_ir": BELL, "backend": "ibm_fez"}).status_code == 503
    assert client.post("/execute", json=_body("ibm_fez")).status_code == 503
    ok = client.post("/execute", json=_body("aer"))
    assert ok.status_code == 200 and ok.json()["compile_report"] is None and sum(ok.json()["counts"].values()) == 300
    preview = client.post("/transpile", json={"concept_ir": BELL, "backend": "ionq_sim_forte-1"}).json()
    assert preview["ok"] and preview["gateset"] == "qis"

    sent = {}

    def submit(self, ionq_input, shots, backend, label, noise_model=None, seed=None):
        sent.update(input=ionq_input, backend=backend, noise_model=noise_model)
        self.last_submit = {"http_status": 200, "response": {"id": "job-off", "status": "submitted",
                                                              "backend": "simulator"}}
        return "job-off"

    def status(self, job_id, backend_label=""):
        return _FakeStatus({"id": job_id, "status": "completed", "backend": "simulator", "shots": 300,
                            "noise": {"model": "forte-1"}})

    monkeypatch.setattr(ionq_runner.IonQRunner, "submit_target", submit)
    monkeypatch.setattr(ionq_runner.IonQRunner, "get_job_status", status)
    r = client.post("/execute", json=_body("ionq_sim_forte-1"))
    assert r.status_code == 200, r.text
    assert sent["noise_model"] == "forte-1" and sent["input"]["gateset"] == "qis"
    j = client.get("/job/job-off").json()
    assert j["status"] == "completed" and sum(j["counts"].values()) == 300


def test_engine_down_is_a_clear_503(engine_settings):
    engine_client.use_transport(StubEngine(down=True))
    r = client.post("/transpile", json={"concept_ir": BELL, "backend": "ibm_fez"})
    assert r.status_code == 503 and "can't be reached" in r.json()["detail"]
    assert client.get("/backends").json()["engine"]["ok"] is False


def test_a_circuit_that_changed_in_transit_is_refused(engine_settings):
    engine_client.use_transport(StubEngine(tamper=True))
    rep = client.post("/transpile", json={"concept_ir": BELL, "backend": "ibm_fez"}).json()
    assert rep["ok"] is False and "doesn't match" in rep["blocking"][0]
    assert client.post("/execute", json=_body("ionq_qpu_forte-1")).status_code in (400, 403)


def test_the_engine_key_stays_on_the_server(engine_settings):
    stub = StubEngine()
    engine_client.use_transport(stub)
    r = client.get("/backends")
    assert backend_app.settings.ENGINE_API_KEY not in r.text
    assert stub.headers and all(h.get("X-API-Key") == backend_app.settings.ENGINE_API_KEY for h in stub.headers)
    from runlog import redact
    assert backend_app.settings.ENGINE_API_KEY not in json.dumps(redact({"note": backend_app.settings.ENGINE_API_KEY}))


def test_ionq_qubit_counts_are_mapped_onto_clbits():
    assert remap_qubit_counts({"101": 7, "001": 3}, 3, {0: 2, 1: 0}, 2) == {"11": 7, "10": 3}


@pytest.fixture()
def live_engine(engine_settings):
    pytest.importorskip("qc_engine", reason="the compile engine package isn't installed (it is private)")
    from qc_engine.service import app as engine_app
    from qc_engine.service.auth import KeyStore, new_key
    key, rec = new_key("quantumcanvas tests", "education", per_minute=10_000, per_day=1_000_000)
    engine_app.set_store(KeyStore({rec.id: rec}))
    backend_app.settings.ENGINE_URL = "http://testserver"
    backend_app.settings.ENGINE_API_KEY = key
    engine_client.use_transport(TestClient(engine_app.app))
    yield
    engine_app.set_store(None)


def test_live_listing_overlays_ionq_availability(live_engine, monkeypatch):
    monkeypatch.setattr(backend_app.settings, "IONQ_API_KEY", "", raising=False)
    r = client.get("/backends").json()
    by = {b["id"]: b for b in r["backends"]}
    assert r["engine"]["ok"] and len(by) >= 16
    assert by["ibm_fez"]["unavailable"] is None and "API key" in by["ionq_sim_aria-1"]["unavailable"]
    assert client.get("/backends/ibm_fez").json()["device"]["qubits"] == 156


def test_live_transpile_is_side_effect_free(live_engine, tmp_path):
    r = client.post("/transpile", json={"concept_ir": BELL, "backend": "ibm_pittsburgh", "seed": 3})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["ok"] and rep["seed"] == 3
    assert next(c for c in rep["checks"] if c["check"] == "engine received this exact circuit")["ok"] is True
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("backend", ["ibm_fez", "braket_local", "aer"])
def test_live_execute_on_engine_simulators(live_engine, backend):
    r = client.post("/execute", json=_body(backend, seed=42))
    assert r.status_code == 200, r.text
    data = r.json()
    assert sum(data["counts"].values()) == 300 and data["compile_report"]["ok"]
    flags = {f["flag"] for f in data["flags"]}
    assert not flags & {"backend_mismatch", "backend_executed_unknown", "result_inconsistent", "code_mismatch"}, flags
    rec = client.get(f"/runs/{data['record_id']}").json()
    assert rec["compile"]["target"]["backend"]["id"] == backend
    if backend == "ibm_fez":
        assert "fake_fez" in rec["execution"]["backend_executed"]
        obs = next(c for c in rec["results"]["math_log"]["checks"] if c["check"].startswith("observed"))
        assert obs["ok"] is None and "noisy backend" in obs["check"]


def test_live_dynamic_circuits(live_engine):
    tele = make_doc(3, teleport_doc(1.1), 3)
    for backend in ("ibm_fez", "ibm_miami", "braket_local"):
        rep = client.post("/transpile", json={"concept_ir": tele, "backend": backend, "seed": 2}).json()
        assert rep["ok"], (backend, rep["blocking"])
    r = client.post("/execute", json=_body("ibm_miami", doc=RESET))
    assert r.status_code == 400 and "Reset" in r.json()["detail"]
    assert client.post("/execute", json=_body("ibm_nowhere")).status_code == 400


def test_live_classic_mode_circuit(live_engine):
    from pathlib import Path
    code = json.loads((Path(__file__).parent / "fixtures" / "legacy" / "grover_3q_mark_q3.json")
                      .read_text(encoding="utf-8"))["qiskit"]
    rep = client.post("/transpile", json={"qiskit_py": code, "backend": "ionq_sim_forte-1", "gateset": "native"}).json()
    assert rep["ok"] and all(c["ok"] is True for c in rep["checks"]), rep["checks"]


def test_live_hardware_is_gated(live_engine, monkeypatch):
    monkeypatch.setattr(backend_app.settings, "ALLOW_QPU_SUBMIT", "off", raising=False)
    for b in ("ionq_qpu_forte-1", "ionq_qpu_forte-enterprise-1", "qpu"):
        assert client.post("/execute", json=_body(b)).status_code == 403


class _FakeStatus:
    def __init__(self, job):
        self.job_id, self.status, self.raw_response = job["id"], job["status"], job
        self.counts = {"00": 140, "11": 150, "01": 10} if job["status"] == "completed" else None

    @property
    def is_terminal(self):
        return self.status in ("completed", "failed", "canceled")


@pytest.mark.parametrize("returned_model,flag", [("aria-1", None), ("ideal", "noise_model_mismatch"),
                                                 (None, "noise_model_unconfirmed")])
def test_live_ionq_noisy_job_flow(live_engine, monkeypatch, returned_model, flag):
    import ionq_runner
    monkeypatch.setattr(backend_app.settings, "IONQ_API_KEY", "test-key", raising=False)
    sent = {}

    def submit(self, ionq_input, shots, backend, label, noise_model=None, seed=None):
        sent.update(input=ionq_input, backend=backend, noise_model=noise_model)
        self.last_submit = {"http_status": 200, "response": {"id": "job-1", "status": "submitted",
                                                              "backend": "simulator"}}
        return "job-1"

    def status(self, job_id, backend_label=""):
        job = {"id": job_id, "status": "completed", "backend": "simulator", "shots": 300}
        if returned_model:
            job["noise"] = {"model": returned_model}
        return _FakeStatus(job)

    monkeypatch.setattr(ionq_runner.IonQRunner, "submit_target", submit)
    monkeypatch.setattr(ionq_runner.IonQRunner, "get_job_status", status)
    r = client.post("/execute", json=_body("ionq_sim_aria-1", gateset="native"))
    assert r.status_code == 200, r.text
    assert sent["backend"] == "simulator" and sent["noise_model"] == "aria-1"
    assert sent["input"]["gateset"] == "native" and {g["gate"] for g in sent["input"]["circuit"]} <= {"gpi", "gpi2", "ms"}
    j = client.get("/job/job-1").json()
    assert j["status"] == "completed" and sum(j["counts"].values()) == 300
    flags = {f["flag"] for f in j["flags"]}
    assert (flag in flags) if flag else not (flags & {"noise_model_mismatch", "noise_model_unconfirmed"})
    assert "backend_mismatch" not in flags
