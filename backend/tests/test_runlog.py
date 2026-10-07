"""Run logging (plan 9c): replay, round-trip, backend mismatch, compile errors, redaction, append-only, blobs."""
import copy
import gzip
import json
from pathlib import Path

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import app as backend_app  # noqa: E402
import executor  # noqa: E402
from conftest import make_doc, node  # noqa: E402
from concepts.migrate import migrate_legacy_ir  # noqa: E402
from config import settings  # noqa: E402
from runlog import RecordInvalid, RunRecorder, RunStore, redact, redact_text  # noqa: E402
from runlog.replay import canvas_to_ir, replay  # noqa: E402
from runlog.store import validate_record  # noqa: E402

client = TestClient(backend_app.app)
FIX = Path(__file__).parent / "fixtures"
REVIEWED = json.loads((FIX / "runs" / "f9e60a7115d2.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LOG_DIR", str(tmp_path), raising=False)
    executor.JOB_MAP.clear()
    return tmp_path


# the same shape the browser sends (frontend/js/concepts.js snapshot): nodes carry a click-order `seq`
NODES = [
    {"id": "N1", "op": "encode", "targets": [1], "controls": [], "ancillas": [], "classical": [], "seq": 0,
     "params": {"method": "angle", "scaling": "arcsin_sqrt", "data": [0.2]}, "condition": None, "body": None, "ref": None, "repeat": 1, "metadata": {"user_created": True}},
    {"id": "N2", "op": "shake", "targets": [0], "controls": [], "ancillas": [], "classical": [], "seq": 1,
     "params": {}, "condition": None, "body": None, "ref": None, "repeat": 1, "metadata": {"user_created": True}},
    {"id": "N3", "op": "entangle", "targets": [0, 1], "controls": [], "ancillas": [], "classical": [], "seq": 2,
     "params": {"style": "cx"}, "condition": None, "body": None, "ref": None, "repeat": 1, "metadata": {"user_created": True}},
    {"id": "N4", "op": "measure", "targets": [0, 1], "controls": [], "ancillas": [], "classical": [0, 1], "seq": 3,
     "params": {}, "condition": None, "body": None, "ref": None, "repeat": 1, "metadata": {"user_created": True}},
]
LEGACY = {"qubits": [{"id": "q1", "taggedOps": []}, {"id": "q2", "taggedOps": []}], "edges": []}
HISTORY = [{"t": "2026-10-08T10:00:00.000Z", "type": "add", "id": "N1", "op": "encode"},
           {"t": "2026-10-08T10:00:05.000Z", "type": "add", "id": "N7", "op": "flip"},
           {"t": "2026-10-08T10:00:09.000Z", "type": "remove", "id": "N7", "op": "flip"}]


def snapshot(nodes=NODES):
    return {"qubits": [{"id": "q1", "label": "Q1", "ops": []}, {"id": "q2", "label": "Q2", "ops": []}], "edges": [],
            "concepts": {"nodes": nodes, "nextNode": 5, "legacy_ir": LEGACY, "classical_bits": 0, "history": HISTORY}}


def compile_doc(nodes=NODES):
    from concepts.migrate import merge_canvas
    return client.post("/compile", json={"legacy_ir": LEGACY, "nodes": nodes}).json()["document"]


BELL = make_doc(2, [node(1, "shake", [0]), node(2, "entangle", [0, 1]), node(3, "measure", [0, 1], classical=[0, 1])], 2)


def body(backend="aer", doc=None, canvas=None, **extra):
    doc = doc or compile_doc()
    return {"canvas_json": json.dumps(canvas or snapshot()), "ir_json": json.dumps(doc), "pseudocode_txt": "p",
            "qiskit_py": "# displayed copy", "backend": backend, "shots": 600, "concept_ir": doc, **extra}


def load(rid, revision=None):
    return executor.store().load(rid, revision)


# ── record v2: content ───────────────────────────────────────────────
def test_aer_run_produces_a_complete_validated_record():
    r = client.post("/execute", json=body()).json()
    rec = load(r["record_id"])
    validate_record(rec)
    assert rec["schema"] == "quantumcanvas.run/v2" and rec["status"] == "ok" and rec["revision"] == 1
    ex = rec["execution"]
    assert ex["backend_requested"] == "aer" and ex["backend_executed"] == "aer_simulator"        # from Aer's own result
    assert isinstance(ex["seed"], int) and ex["shots"] == 600
    assert ex["transpiled"]["depth"] > 0 and "openqasm" in ex["transpiled"]["format"] and ex["transpiled"]["basis_gates"]
    assert ex["raw_provider_response"]["backend_name"] == "aer_simulator"
    assert {"transpile_ms", "execute_ms", "total_ms", "compile"} <= set(ex["timing"])
    v = rec["versions"]
    assert v["qiskit"] and v["qiskit_aer"] and v["math_layer"] and v["compiler"] and v["ir_schema"] == "0.3" and v["app_git_sha"]
    assert rec["compile"]["gates"] and rec["compile"]["trace"] and rec["compile"]["qasm3"].startswith("OPENQASM 3")
    assert rec["compile"]["qiskit_py"] and rec["compile"]["qiskit_py_displayed"] == "# displayed copy"
    assert rec["results"]["counts"] and rec["results"]["math_log"]["steps"] and rec["results"]["result_check"]["ok"] is True
    assert rec["flags"] == [] and rec["errors"] == []
    assert rec["identity"]["circuit_hash"] and rec["identity"]["circuit_folder"] and rec["identity"]["user"] == "anonymous"
    assert r["math"]["ran"] and r["math"]["failed_checks"] == []


def test_canvas_json_saved_with_the_run_carries_the_steps():
    rec = load(client.post("/execute", json=body()).json()["record_id"])
    canvas = rec["input"]["canvas_json"]
    assert [n["id"] for n in canvas["concepts"]["nodes"]] == ["N1", "N2", "N3", "N4"]   # not empty, unlike f9e60a7115d2


def test_edit_history_explains_deleted_nodes():
    rec = load(client.post("/execute", json=body()).json()["record_id"])
    kinds = [(h["id"], h["type"]) for h in rec["edit_history"]]
    assert ("N7", "add") in kinds and ("N7", "remove") in kinds                          # the gap is explained


# ── plan 9c required tests ───────────────────────────────────────────
def test_replay_recompiles_to_identical_code_and_distribution_and_reproduces_counts():
    rec = load(client.post("/execute", json=body()).json()["record_id"])
    out = replay(rec)
    assert out == {"compiled_ok": True, "roundtrip_identical": True, "qiskit_identical": True,
                   "distribution_identical": True, "counts_reproduced": True}


def test_replay_endpoint():
    rid = client.post("/execute", json=body()).json()["record_id"]
    out = client.post(f"/runs/{rid}/replay").json()
    assert out["qiskit_identical"] and out["distribution_identical"] and out["counts_reproduced"] and out["roundtrip_identical"]
    assert client.get(f"/runs/{rid}").json()["run_id"] == rid
    assert client.get("/runs/doesnotexist").status_code == 404


def test_canvas_to_ir_round_trip_equals_stored_ir():
    doc = compile_doc()
    assert canvas_to_ir(snapshot()) == doc


def test_round_trip_would_have_failed_on_the_reviewed_run():
    """f9e60a7115d2 saved an EMPTY canvas: its canvas cannot be turned back into the IR it ran."""
    canvas = json.loads(REVIEWED["canvas_json"])
    assert all(q["ops"] == [] for q in canvas["qubits"]) and "concepts" not in canvas
    assert canvas_to_ir(canvas) is None                                                  # detected, not silently "fine"
    assert len(json.loads(REVIEWED["ir_json"])["operations"]) == 7


def test_round_trip_detects_a_snapshot_that_disagrees_with_the_ir():
    rec = load(client.post("/execute", json=body()).json()["record_id"])
    rec["input"]["canvas_json"]["concepts"]["nodes"] = rec["input"]["canvas_json"]["concepts"]["nodes"][:-1]
    assert replay(rec)["roundtrip_identical"] is False


class FakeIonQ:
    """Stands in for the provider; `executed` is what the PROVIDER says it ran on."""
    executed = "simulator"

    def __init__(self, *a, **k):
        self.last_submit = None
        self.last_status = None

    def _submit(self, backend):
        self.last_submit = {"http_status": 200, "response": {"id": "job-1", "status": "submitted", "backend": FakeIonQ.executed}}
        return "job-1"

    def submit_qpu(self, **k):
        return self._submit("qpu.forte-1")

    def submit_ionq_sim(self, **k):
        return self._submit("simulator")

    def run_simulator(self, **k):
        self.last_submit = {"http_status": 200, "response": {"id": "job-9", "backend": FakeIonQ.executed}}
        self.last_status = {"id": "job-9", "status": "completed", "backend": FakeIonQ.executed}
        return {"00": 300, "11": 300}


def test_backend_mismatch_qpu_requested_simulator_executed_is_flagged(monkeypatch):
    import ionq_runner
    monkeypatch.setattr(ionq_runner, "IonQRunner", FakeIonQ)
    FakeIonQ.executed = "simulator"                                    # the real routing bug: asked for the QPU, got a simulator
    r = client.post("/execute", json=body("qpu")).json()
    rec = load(r["record_id"])
    assert rec["execution"]["backend_requested"] == "qpu" and rec["execution"]["backend_executed"] == "simulator"
    assert [f["flag"] for f in rec["flags"]] == ["backend_mismatch"] and "qpu" in rec["flags"][0]["detail"]
    assert r["flags"][0]["flag"] == "backend_mismatch"                 # also visible to the UI straight away


def test_matching_backend_is_not_flagged(monkeypatch):
    import ionq_runner
    monkeypatch.setattr(ionq_runner, "IonQRunner", FakeIonQ)
    FakeIonQ.executed = "qpu.forte-1"
    assert load(client.post("/execute", json=body("qpu", doc=BELL)).json()["record_id"])["flags"] == []
    FakeIonQ.executed = "simulator"
    rec = load(client.post("/execute", json=body("simulator", doc=BELL)).json()["record_id"])
    assert rec["flags"] == [] and rec["execution"]["backend_executed"] == "simulator" and rec["status"] == "ok"


def test_unnamed_provider_backend_is_flagged_not_assumed(monkeypatch):
    import ionq_runner

    class Silent(FakeIonQ):
        def _submit(self, backend):
            self.last_submit = {"http_status": 200, "response": {"id": "job-2", "status": "submitted"}}
            return "job-2"
    monkeypatch.setattr(ionq_runner, "IonQRunner", Silent)
    rec = load(client.post("/execute", json=body("qpu")).json()["record_id"])
    assert rec["execution"]["backend_executed"] is None and rec["flags"][0]["flag"] == "backend_executed_unknown"


def test_async_job_appends_a_second_revision_with_results_and_executed_backend(monkeypatch):
    import ionq_runner
    from ionq_runner import JobStatus
    monkeypatch.setattr(ionq_runner, "IonQRunner", FakeIonQ)
    FakeIonQ.executed = "simulator"
    r = client.post("/execute", json=body("ionq", doc=BELL)).json()
    rid = r["record_id"]
    assert r["job_id"] == "job-1" and load(rid)["status"] == "submitted" and load(rid)["revision"] == 1
    done = JobStatus("job-1", "completed", {"00": 290, "11": 310}, {"id": "job-1", "status": "completed", "backend": "simulator", "shots": 600})
    extra = executor.on_job_status("job-1", done)
    rec = load(rid)
    assert rec["revision"] == 2 and rec["status"] == "ok" and rec["results"]["counts"] == {"00": 290, "11": 310}
    assert rec["execution"]["provider_job_id"] == "job-1" and rec["execution"]["provider_status"] == "completed"
    assert rec["results"]["result_check"]["ok"] is True and extra["record_id"] == rid
    assert len(executor.store().find(rid)) == 2                       # append-only: both revisions exist
    assert load(rid, revision=1)["status"] == "submitted"


def test_async_job_failure_is_recorded(monkeypatch):
    import ionq_runner
    from ionq_runner import JobStatus
    monkeypatch.setattr(ionq_runner, "IonQRunner", FakeIonQ)
    rid = client.post("/execute", json=body("ionq", doc=BELL)).json()["record_id"]
    executor.on_job_status("job-1", JobStatus("job-1", "failed", None, {"id": "job-1", "status": "failed", "backend": "simulator"}))
    rec = load(rid)
    assert rec["status"] == "error" and rec["errors"][-1]["stage"] == "fetch"


def test_validation_failure_still_produces_a_record():
    bad = make_doc(1, [node(1, "flip", [4])])
    r = client.post("/execute", json=body(doc=bad))
    assert r.status_code == 400
    rec = _only_record()
    assert rec["status"] == "error" and rec["errors"][0]["stage"] == "validate" and rec["errors"][0]["code"] == "E_QUBIT_RANGE"
    assert rec["input"]["validator_errors"] and rec["input"]["ir_json"]                # inputs kept for the audit


def test_injected_compile_error_produces_a_compile_stage_record(monkeypatch):
    import concepts

    def boom(*a, **k):
        raise RuntimeError("injected compile failure")
    monkeypatch.setattr(concepts, "compile_document", boom)
    r = client.post("/execute", json=body())
    assert r.status_code == 500
    rec = _only_record()
    assert rec["status"] == "error" and rec["errors"][0]["stage"] == "compile" and "injected" in rec["errors"][0]["message"]
    assert "Traceback" not in r.text and "Traceback" not in json.dumps(rec)           # traces go to server logs only


def test_ionq_refusal_produces_a_compile_stage_record():
    doc = make_doc(1, [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]), node(3, "reset", [0])], 1)
    r = client.post("/execute", json=body("ionq", doc=doc))
    assert r.status_code == 400 and "Aer" in r.json()["detail"]
    rec = _only_record()
    assert rec["errors"][0]["stage"] == "compile" and rec["errors"][0]["code"] == "W_BACKEND_UNSUPPORTED"


def _only_record():
    files = sorted(Path(settings.LOG_DIR).glob("runs/*/runrecord_*.json"))
    assert len(files) == 1, files
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    validate_record(rec)
    return rec


# ── redaction ────────────────────────────────────────────────────────
FAKE_KEY = "sk-fake-DO-NOT-LEAK-1234567890abcdef"


def test_fake_api_key_never_reaches_a_record_or_a_log_line(monkeypatch, capsys):
    monkeypatch.setenv("LLM_API_KEY", FAKE_KEY)
    canvas = snapshot(); canvas["note"] = f"token={FAKE_KEY}"; canvas["owner"] = "student@example.edu"; canvas["api_key"] = "abc"
    r = client.post("/execute", json=body(canvas=canvas, pseudocode_txt=f"Authorization: Bearer {FAKE_KEY}")).json()
    text = json.dumps(load(r["record_id"]))
    assert FAKE_KEY not in text and "student@example.edu" not in text and '"abc"' not in text
    assert "[REDACTED" in text
    on_disk = "".join(p.read_text(encoding="utf-8") for p in Path(settings.LOG_DIR).rglob("*") if p.is_file() and p.suffix in (".json", ".jsonl"))
    assert FAKE_KEY not in on_disk and FAKE_KEY not in capsys.readouterr().out


def test_redact_unit_cases():
    assert redact({"Authorization": "Bearer abcdef1234567890", "ok": 1})["Authorization"] == "[REDACTED]"
    assert "[REDACTED" in redact_text("key sk-abcdefghijklmnop1234 and gsk_abcdefghijklmnop1234 and a@b.co")
    assert redact_text("mongodb+srv://user:pw123456@cluster.mongodb.net/x").count("pw123456") == 0
    assert redact({"counts": {"00": 3}})["counts"] == {"00": 3}                          # numbers and counts are untouched
    sec = "very-secret-value-123"
    assert sec not in json.dumps(redact({"a": {"b": [f"x {sec} y"]}}, secrets=[sec]))


# ── schema, save failures, append-only, blobs ─────────────────────────
def minimal_record():
    rec = RunRecorder(backend_requested="aer", shots=10)
    rec.identity.update(circuit_hash="h" * 64, circuit_folder="hhhhhhhhhhhh")
    rec.finish()
    return rec.to_record()


def test_record_that_fails_the_schema_is_rejected_loudly(tmp_path):
    rec = minimal_record()
    rec["errors"] = [{"stage": "not-a-stage", "code": "x", "message": "y"}]
    with pytest.raises(RecordInvalid) as e:
        RunStore(tmp_path).save(rec)
    assert "errors" in str(e.value)
    assert not list(tmp_path.rglob("runrecord_*"))                                       # nothing half-written


def test_failed_save_is_surfaced_to_the_user_not_swallowed(monkeypatch):
    def bad_save(self, rec):
        raise RecordInvalid("deliberately broken")
    monkeypatch.setattr(RunStore, "save", bad_save)
    r = client.post("/execute", json=body()).json()
    assert r["counts"] and "could not be saved" in r["save_error"] and "deliberately broken" in r["save_error"]


def test_records_are_append_only(tmp_path):
    st, rec = RunStore(tmp_path), minimal_record()
    st.save(rec)
    with pytest.raises(RecordInvalid):
        st.save(rec)                                                                      # same revision twice


def test_big_blobs_are_compressed_with_a_pointer_not_truncated(tmp_path):
    rec = minimal_record()
    big = {"submit": {"x": "y" * 200_000}}
    rec["execution"]["raw_provider_response"] = big
    st = RunStore(tmp_path)
    path = st.save(rec)
    small = json.loads(path.read_text(encoding="utf-8"))
    ref = small["execution"]["raw_provider_response"]
    assert ref["$ref"].endswith(".json.gz") and ref["bytes"] > 100_000 and len(ref["sha256"]) == 64
    assert st.load(rec["run_id"])["execution"]["raw_provider_response"] == big          # full fidelity on read
    blob = path.parent / ref["$ref"]
    blob.write_bytes(gzip.compress(json.dumps({"tampered": 1}).encode()))
    with pytest.raises(RecordInvalid):
        st.load(rec["run_id"])                                                            # checksum catches tampering


def test_structured_server_log_lines_join_to_the_run():
    r = client.post("/execute", json=body()).json()
    lines = [json.loads(l) for l in (Path(settings.LOG_DIR) / "server.jsonl").read_text(encoding="utf-8").splitlines()]
    mine = [l for l in lines if l.get("run_id") == r["record_id"]]
    assert {"ts", "level", "run_id", "stage", "event", "duration_ms"} <= set(mine[0])
    assert {"stage_start", "stage_end", "record_saved"} <= {l["event"] for l in mine}
    assert any(l["stage"] == "compile" and l["event"] == "stage_end" and l["duration_ms"] is not None for l in mine)


# ── classic mode, research logging ───────────────────────────────────
def test_classic_run_gets_a_record_and_a_math_check():
    fx = json.loads((FIX / "legacy" / "bell_pair.json").read_text(encoding="utf-8"))
    payload = {"canvas_json": json.dumps({"qubits": [], "edges": []}), "ir_json": json.dumps(fx["ir"]), "pseudocode_txt": "",
               "qiskit_py": fx["qiskit"], "backend": "aer", "shots": 500}
    r = client.post("/execute", json=payload).json()
    rec = load(r["record_id"])
    assert rec["status"] == "ok" and rec["results"]["math_log"] and rec["results"]["result_check"]["ok"] is True
    assert rec["execution"]["backend_executed"] == "aer_simulator" and rec["execution"]["seed"] is not None


def test_research_logging_is_off_by_default_and_needs_consent(monkeypatch):
    ev = {"study_id": "pilot-1", "consent": True, "session": "abc", "event": "how_opened", "data": {"step": "N3"}}
    assert client.post("/research/event", json=ev).json()["stored"] is False            # default: off
    monkeypatch.setattr(settings, "RESEARCH_LOGGING", "on", raising=False)
    assert client.post("/research/event", json={**ev, "consent": False}).json()["stored"] is False
    assert client.post("/research/event", json={**ev, "study_id": "../etc"}).status_code == 400
    assert client.post("/research/event", json=ev).json()["stored"] is True
    row = json.loads((Path(settings.LOG_DIR) / "research" / "pilot-1.jsonl").read_text(encoding="utf-8"))
    assert "abc" not in json.dumps(row) and len(row["pid"]) == 16                        # pseudonymous
    assert not list(Path(settings.LOG_DIR).glob("runs/*/runrecord_*"))                   # stored apart from run records


def test_provider_counts_that_contradict_the_circuit_are_flagged(monkeypatch):
    """The math layer's result check turns a stub / wrong-backend result into a visible flag on the run."""
    import ionq_runner

    class Stub(FakeIonQ):
        def run_simulator(self, **k):
            self.last_submit = {"http_status": 200, "response": {"id": "j", "backend": "simulator"}}
            self.last_status = {"id": "j", "status": "completed", "backend": "simulator"}
            return {"00": 300, "01": 300}                          # impossible for a Bell pair
    monkeypatch.setattr(ionq_runner, "IonQRunner", Stub)
    rec = load(client.post("/execute", json=body("simulator", doc=BELL)).json()["record_id"])
    assert "result_inconsistent" in [f["flag"] for f in rec["flags"]]
    assert "predicted probability 0" in rec["results"]["result_check"]["detail"]
