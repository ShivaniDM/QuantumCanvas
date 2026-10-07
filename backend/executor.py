"""Execution pipeline with full run logging (plan 9c). app.py's /execute and /job call into here.

Every execution produces ONE run record (append-only revisions) validated against the v2 schema, including runs
that fail at validate / compile / submit. The record names the backend the PROVIDER says executed, not the one we
asked for, so a QPU request that ran on a simulator is flagged on every run.
"""
from __future__ import annotations

import json
import time

from fastapi import HTTPException

from config import settings
from logger import ArtifactLogger, compute_circuit_hash
from runlog import RecordInvalid, RunRecorder, RunStore, log_event
from runlog.record import executor_matches

JOB_MAP: dict[str, dict] = {}          # job_id -> {"rec": RunRecorder, "folder": str, "circuit_hash": str, "backend": str}


def store() -> RunStore:
    return RunStore(settings.LOG_DIR)


def _json_or_str(s):
    if not isinstance(s, str):
        return s
    try:
        return json.loads(s)
    except Exception:
        return s


def save_record(rec: RunRecorder, response: dict | None = None) -> str | None:
    """Validate + write the next revision. Failure is surfaced (response['save_error']) and logged, never dropped."""
    try:
        rec_dict = rec.to_record()
        store().save(rec_dict)
        return None
    except (RecordInvalid, OSError) as e:
        msg = f"The run finished but its record could not be saved: {e}"
        log_event("record_save_failed", level="error", run_id=rec.run_id, stage="save", message=str(e))
        if response is not None:
            response["save_error"] = msg
        return msg


def _math(rec: RunRecorder, ir_doc: dict | None, qiskit_py: str | None, counts, code_check: bool) -> dict:
    """Run the math layer; never fails the run. Returns a small summary for the UI."""
    summary = {"ran": False}
    if ir_doc is None:
        return summary
    try:
        from mathlayer import analyze
        with rec.stage("math"):
            log = analyze({"run_id": rec.run_id, "ir_json": ir_doc, "qiskit_py": qiskit_py or "", "results": counts},
                          code_check=code_check)
        rec.results["math_log"] = log
        failed = [c["check"] for c in log["checks"] if c["ok"] is False]
        obs = next((c for c in log["checks"] if c["check"].startswith("observed")), None)
        rec.results["result_check"] = obs
        if any(c.startswith("code") or "parsed" in c for c in failed):
            rec.flag("code_mismatch", "; ".join(c for c in failed if c.startswith("code") or "parsed" in c)[:300])
        if obs and obs["ok"] is False:
            rec.flag("result_inconsistent", obs.get("detail", "observed counts disagree with the exact prediction"))
        broken = sorted({s["id"] for s in log["steps"] for c in s["contracts"] if not c["held"]})
        idle = [s["id"] for s in log["steps"] if s.get("affects_result") is False] if log.get("ineffective_together") else []
        summary = {"ran": True, "failed_checks": failed, "result_check": obs, "broken_contract_steps": broken,
                   "idle_steps": idle, "predicted": log.get("predicted")}
    except Exception:
        pass                                   # recorded by rec.stage(); the run result stands
    return summary


def _fill_input(rec: RunRecorder, req: dict, concept_ir_doc):
    canvas = _json_or_str(req.get("canvas_json"))
    rec.input.update(canvas_json=canvas, ir_json=concept_ir_doc if concept_ir_doc is not None else _json_or_str(req.get("ir_json")),
                     pseudocode_txt=req.get("pseudocode_txt"))
    hist = ((canvas or {}).get("concepts") or {}).get("history") if isinstance(canvas, dict) else None
    if isinstance(hist, list):
        rec.edit_history = hist[-2000:]


def _legacy_ir_doc(req: dict):
    """Classic-mode runs: migrate the legacy IR so the math layer can check them too."""
    try:
        from concepts.migrate import migrate_legacy_ir
        return migrate_legacy_ir(json.loads(req["ir_json"]))
    except Exception:
        return None


def execute(req: dict) -> dict:
    t_total = time.perf_counter()
    backend, shots = req["backend"], req.get("shots", 1000)
    rec = RunRecorder(backend_requested=backend, shots=shots, session_id=req.get("session_id"),
                      user=req.get("user") or "anonymous", parent_run_id=req.get("parent_run_id"))
    circuit_hash = compute_circuit_hash(req["ir_json"])
    logger = ArtifactLogger()
    folder, _ = logger.open_run(circuit_hash)
    rec.identity.update(circuit_hash=circuit_hash, circuit_folder=folder)
    response = {"run_id": folder, "record_id": rec.run_id, "flags": [], "status": "ok"}
    log_event("execute_start", run_id=rec.run_id, backend=backend, shots=shots, circuit_hash=circuit_hash[:12])

    concept = None
    concept_doc = None
    try:
        if not logger.has_core_artifacts():
            logger.save("canvas.json", req["canvas_json"]); logger.save("ir.json", req["ir_json"])
            logger.save("pseudocode.txt", req["pseudocode_txt"]); logger.save("qiskit.py", req["qiskit_py"])
        logger.record_run(circuit_hash, backend, shots)

        # ── validate + compile ────────────────────────────────────────
        _fill_input(rec, req, req.get("concept_ir"))        # input is recorded FIRST, so even a failed compile is auditable
        rec.compile["qiskit_py_displayed"] = req.get("qiskit_py")
        if req.get("concept_ir") is not None:
            from concepts import compile_document
            ionq_target = backend in ("simulator", "ionq", "qpu")
            try:
                with rec.stage("compile"):
                    concept = compile_document(req["concept_ir"], backend="ionq" if ionq_target else None, with_qasm=True)
            except Exception as e:
                _fail(rec, response, logger, f"Compiling this circuit failed unexpectedly ({type(e).__name__}).", 500)
            rec.input["validator_errors"] = [e.to_dict() for e in concept.errors]
            rec.input["validator_warnings"] = [w.to_dict() for w in concept.warnings]
            concept_doc = concept.document
            if not concept.ok:
                rec.error("validate", concept.errors[0].code, concept.errors[0].message)
                _fail(rec, response, logger, "; ".join(e.message for e in concept.errors), 400)
            logger.save("concept_ir.json", req["concept_ir"])
            rec.compile.update(ir_hash=circuit_hash, gates=concept.gates, trace=[list(t) for t in concept.trace],
                               qiskit_py=concept.qiskit_py, qasm3=concept.qasm3, pseudocode=concept.pseudocode,
                               ionq_circuit=concept.ionq)
            if ionq_target and concept.ionq is None:
                msg = " ".join(w.message for w in concept.warnings if w.code == "W_BACKEND_UNSUPPORTED") or "This circuit can't be lowered for IonQ."
                rec.error("compile", "W_BACKEND_UNSUPPORTED", msg)
                _fail(rec, response, logger, msg, 400)
        else:
            rec.compile.update(ir_hash=circuit_hash, qiskit_py=req.get("qiskit_py"))
            rec.input["validator_errors"], rec.input["validator_warnings"] = [], []
        if concept_doc is not None:
            rec.input["ir_json"] = concept_doc                # the normalised document that was actually compiled
        ionq_circuit = concept.ionq if concept else None

        # ── execute ───────────────────────────────────────────────────
        if backend == "aer":
            counts = _run_aer(rec, req, concept, logger)
            _after_results(rec, response, logger, counts, concept, concept_doc, req)
        else:
            _run_ionq(rec, req, ionq_circuit, logger, response, circuit_hash, folder, concept, concept_doc)
    except HTTPException:
        raise
    except Exception as e:
        rec.error("submit", type(e).__name__, str(e), exc=e)
        logger.error(str(e))
        rec.finish("error")
        save_record(rec, response)
        raise HTTPException(status_code=500, detail=str(e))
    return response


def _fail(rec, response, logger, message, code):
    logger.error(message)
    rec.finish("error")
    save_record(rec, response)
    raise HTTPException(status_code=code, detail=message)


def _run_aer(rec, req, concept, logger):
    from aer_runner import run_aer_detailed, _strip_run_block
    with rec.stage("submit"):
        if concept:
            from concepts.emit_qiskit import build_circuit
            qc = build_circuit(concept.lowered)
        else:                                            # classic path: the generated text, as before
            ns: dict = {}
            exec(compile(_strip_run_block(req["qiskit_py"]), "<quantumcanvas_qiskit>", "exec"), ns)  # noqa: S102
            qc = ns.get("qc")
            if qc is None:
                raise RuntimeError("Generated code did not define a circuit `qc`.")
        d = run_aer_detailed(qc, rec.execution["shots"], logger=logger)
    ex = rec.execution
    ex.update(backend_executed=d["backend_name"], seed=d["seed"], transpiled=d["transpiled"],
              raw_provider_response=d["raw"], provider_status="completed")
    ex["timing"].update(d["timing"])
    rec.check_executor()
    logger.save("results_aer.json", {**d["counts"], "circuit_hash": rec.identity["circuit_hash"]})
    return d["counts"]


def _after_results(rec, response, logger, counts, concept, concept_doc, req):
    rec.results["counts"] = counts
    if concept_doc is not None:
        summary = _math(rec, concept_doc, concept.qiskit_py, counts, code_check=True)
    else:
        rec.input["ir_migrated"] = _legacy_ir_doc(req)       # classic runs: the Concept IR the math layer checked
        summary = _math(rec, rec.input["ir_migrated"], None, counts, code_check=False)
    rec.finish()
    response.update(counts=counts, status=rec.status, math=summary, flags=rec.flags)
    save_record(rec, response)
    response["flags"] = rec.flags


def _run_ionq(rec, req, ionq_circuit, logger, response, circuit_hash, folder, concept, concept_doc):
    from ionq_runner import IonQRunner
    runner = IonQRunner(api_key=settings.IONQ_API_KEY, endpoint=settings.IONQ_ENDPOINT, logger=logger)
    backend = rec.execution["backend_requested"]
    code, shots = req["qiskit_py"], rec.execution["shots"]
    with rec.stage("submit"):
        if backend == "simulator":
            counts = runner.run_simulator(qiskit_code=code, shots=shots, ionq_circuit=ionq_circuit)
            job = runner.last_status or {}
            sub = (runner.last_submit or {}).get("response", {})
            _provider(rec, sub, job)
            logger.save("results_simulator.json", {**counts, "circuit_hash": circuit_hash})
            rec.check_executor()
            _after_results(rec, response, logger, counts, concept, concept_doc, req)
            return
        fn = runner.submit_ionq_sim if backend == "ionq" else runner.submit_qpu
        job_id = fn(qiskit_code=code, shots=shots, ionq_circuit=ionq_circuit)
    sub = (runner.last_submit or {}).get("response", {})
    _provider(rec, sub, {})
    rec.execution.update(provider_job_id=job_id, provider_status=sub.get("status", "submitted"))
    rec.status = "submitted"
    rec.check_executor()
    JOB_MAP[job_id] = {"rec": rec, "folder": folder, "circuit_hash": circuit_hash, "backend": backend,
                       "concept": concept, "concept_doc": concept_doc, "req": req}
    response.update(job_id=job_id, status="submitted", flags=rec.flags)
    save_record(rec, response)
    response["flags"] = rec.flags


def _provider(rec, submit_resp: dict, job_obj: dict):
    """Take the backend name from the PROVIDER's own objects, never from our request."""
    ex = rec.execution
    executed = (job_obj.get("backend") or job_obj.get("target") or submit_resp.get("backend") or submit_resp.get("target"))
    ex["backend_executed"] = executed
    ex["raw_provider_response"] = {"submit": submit_resp, "job": job_obj} if job_obj else {"submit": submit_resp}
    ex["provider_status"] = job_obj.get("status") or submit_resp.get("status")
    if job_obj.get("id") or submit_resp.get("id"):
        ex["provider_job_id"] = job_obj.get("id") or submit_resp.get("id")
    cost = job_obj.get("cost") or job_obj.get("estimated_cost")
    if cost is not None:
        ex["cost"] = cost if isinstance(cost, dict) else {"value": cost}


def on_job_status(job_id: str, status) -> dict:
    """Called by /job on every poll. On a terminal state, append the final record revision."""
    extra: dict = {}
    entry = JOB_MAP.get(job_id)
    if entry is None:
        log_event("job_unknown", level="warning", job_id=job_id, message="no run record is attached to this job (server restarted?)")
        return extra
    rec: RunRecorder = entry["rec"]
    extra["record_id"] = rec.run_id
    if not status.is_terminal:
        return extra
    job = status.raw_response or {}
    with_stage_error = status.status in ("failed", "canceled", "cancelled")
    try:
        _provider(rec, (rec.execution.get("raw_provider_response") or {}).get("submit", {}), job)
        rec.execution["provider_status"] = status.status
        rec.check_executor()
        if with_stage_error:
            rec.error("fetch", f"job_{status.status}", f"The provider reports the job as {status.status}.")
            rec.finish("error")
        else:
            counts = status.counts or {}
            rec.results["counts"] = counts
            summary = (_math(rec, entry["concept_doc"], entry["concept"].qiskit_py, counts, code_check=True)
                       if entry["concept_doc"] is not None else
                       _math(rec, _legacy_ir_doc(entry["req"]), None, counts, code_check=False))
            extra["math"] = summary
            rec.finish("ok")
    finally:
        err = save_record(rec, extra)
        extra["flags"] = rec.flags
        JOB_MAP.pop(job_id, None)
    return extra
