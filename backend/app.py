"""
QuantumCanvas Backend — FastAPI
Routes:
  POST /log-circuit — explicit "save current state" snapshot (no execution)
  POST /execute      — receive canvas artifacts, run simulator or IonQ, save logs
  GET  /job/{id}     — poll IonQ job status
  POST /cost         — dry-run cost estimate for QPU hardware
  POST /qasm         — export generated Qiskit as OpenQASM 2.0 text
  GET  /runs/{id}    — the stored run record (quantumcanvas.run/v2)
  POST /runs/{id}/replay — recompile a stored run and compare
  POST /explain      — template explanation (+ optional grounded LLM text, claim-checked)
  POST /research/event — consented research events (off by default)
  POST /compile      — Concept IR -> validation, pseudocode, Qiskit, gates + trace (no side effects)
  GET  /problems     — problem bank (statements, allowed concepts, hints; no answers)
  POST /check-problem — grade a Concept IR solution against a problem
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any
import uvicorn

from config      import settings
from logger      import ArtifactLogger, compute_circuit_hash
from ionq_runner import IonQRunner, JobStatus
from concepts    import compile_document
from concepts.migrate import merge_canvas
import problems as problem_bank
import executor
from runlog import log_event

app = FastAPI(title="QuantumCanvas API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten for production
    allow_methods=["POST","GET"],
    allow_headers=["*"],
)

# ── Request / response models ─────────────────────────────────────────

class LogCircuitRequest(BaseModel):
    """Explicit 'Save current state' — snapshot before (or independent of) running anything."""
    canvas_json:    str
    ir_json:        str
    pseudocode_txt: str = ""
    qiskit_py:      str = ""

class LogCircuitResponse(BaseModel):
    ok:            bool
    circuit_hash:  str
    run_id:        str
    path:          str            # e.g. "logs/runs/a1b2c3d4e5f6"
    files:         list[str] = []
    already_saved: bool           # true if this exact circuit was saved before

class ExecuteRequest(BaseModel):
    canvas_json:    str
    ir_json:        str
    pseudocode_txt: str
    qiskit_py:      str
    backend:        str   # "aer" | "simulator" | "ionq" | "qpu"
    shots:          int   = 1000
    session_id:     str | None = None
    user:           str | None = None
    parent_run_id:  str | None = None
    # Optional Concept IR v0.3 document. When present the circuit is compiled from it
    # (no exec() of source text, IonQ gates come straight from the compiler) and
    # qiskit_py is only archived.
    concept_ir:     dict | None = None

class ExecuteResponse(BaseModel):
    run_id:   str                  # circuit folder id (logs/runs/<run_id>/), unchanged for older clients
    record_id: str | None = None   # this execution's run-record id (quantumcanvas.run/v2)
    counts:   dict | None = None   # synchronous result (simulator)
    job_id:   str | None  = None   # async job ID (IonQ hardware)
    status:   str = "ok"
    flags:    list = []            # e.g. backend_mismatch, result_inconsistent, code_mismatch
    math:     dict | None = None   # math-layer summary
    save_error: str | None = None  # set when the run record could not be saved (never silent)

class JobResponse(BaseModel):
    job_id:  str
    status:  str   # submitted | running | completed | failed | canceled
    counts:  dict | None = None
    run_id:  str | None  = None
    error:   str | None  = None
    raw:     dict | None = None   # full IonQ job object (hardware metadata)
    record_id: str | None = None
    flags:   list = []
    math:    dict | None = None
    save_error: str | None = None

class CompileRequest(BaseModel):
    """Either a full Concept IR `document`, or the canvas' legacy IR plus its new concept `nodes`
    (each with a click-order `seq`); the backend merges them."""
    document:       dict | None = None
    legacy_ir:      dict | None = None
    nodes:          list[dict] = []
    classical_bits: int = 0
    backend:        str | None = None     # "ionq" also lowers for IonQ
    qasm:           bool = False

class CheckProblemRequest(BaseModel):
    problem_id: str
    document:   dict

class QasmRequest(BaseModel):
    qiskit_py: str

class QasmResponse(BaseModel):
    qasm:  str  | None = None
    error: str  | None = None

class CostResponse(BaseModel):
    cost_usd:                  float | None = None
    queue_days:                int   | None = None
    target:                    str          = "qpu.forte-1"
    gate_counts:               Any          = None   # shape varies by IonQ version
    predicted_execution_time:  float | None = None
    status:                    str   | None = None
    raw:                       dict  | None = None   # full IonQ estimate response
    error:                     str   | None = None

# ── Routes ────────────────────────────────────────────────────────────

@app.post("/log-circuit", response_model=LogCircuitResponse)
async def log_circuit(req: LogCircuitRequest):
    """
    Save the circuit's current state (canvas/IR/pseudocode/Qiskit) into
    logs/runs/<circuit_hash>/ — independent of running any backend. Same
    circuit content always maps to the same folder, so calling this again
    with no changes is a no-op (already_saved=true), and running a backend
    afterward lands its results in this same folder.
    """
    circuit_hash = compute_circuit_hash(req.ir_json)
    logger = ArtifactLogger()
    run_id, _ = logger.open_run(circuit_hash)

    already_saved = logger.has_core_artifacts()
    files = []
    if not already_saved:
        logger.save("canvas.json",     req.canvas_json)
        logger.save("ir.json",         req.ir_json)
        logger.save("pseudocode.txt",  req.pseudocode_txt)
        logger.save("qiskit.py",       req.qiskit_py)
        logger.save("circuit_hash.txt", circuit_hash)
        files = ["canvas.json", "ir.json", "pseudocode.txt", "qiskit.py"]
        logger.log(f"Circuit state saved — hash={circuit_hash[:12]}…")
    else:
        logger.log(f"Circuit already saved — hash={circuit_hash[:12]}… (no changes)")

    return LogCircuitResponse(
        ok            = True,
        circuit_hash  = circuit_hash,
        run_id        = run_id,
        path          = f"logs/runs/{run_id}",
        files         = files,
        already_saved = already_saved,
    )


@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest):
    """Validate → compile → execute → math-check → save ONE run record (plan 9c). See executor.py."""
    return ExecuteResponse(**executor.execute(req.model_dump()))


# In-memory job→run mapping (production: use a DB or Redis)
_job_run_map: dict[str, dict] = {}

@app.get("/job/{job_id}", response_model=JobResponse)
async def poll_job(job_id: str):
    live = executor.JOB_MAP.get(job_id)
    entry = _job_run_map.get(job_id) or ({"run_id": live["folder"], "backend": live["backend"],
                                          "circuit_hash": live["circuit_hash"]} if live else {})
    run_id       = entry.get("run_id")
    backend      = entry.get("backend", "ionq")
    circuit_hash = entry.get("circuit_hash")
    logger       = ArtifactLogger(run_id=run_id, circuit_hash=circuit_hash) if run_id else ArtifactLogger()

    try:
        runner = IonQRunner(
            api_key  = settings.IONQ_API_KEY,
            endpoint = settings.IONQ_ENDPOINT,
            logger   = logger,
        )
        status: JobStatus = runner.get_job_status(job_id, backend_label=backend)

        if status.is_terminal and status.counts:
            # Distinct name from the submit-ack file (ionq_response_{label}.json,
            # saved in _submit_job) — for QPU jobs both used "qpu" and the
            # completed response silently overwrote the submit ack.
            logger.save(f"ionq_completed_{backend}.json", status.raw_response)
            logger.save(f"results_{backend}.json",        status.counts)
            logger.log(f"Job {job_id} completed — saving artifacts")

        extra = executor.on_job_status(job_id, status)
        return JobResponse(
            job_id = job_id,
            status = status.status,
            counts = status.counts,
            run_id = run_id,
            raw    = status.raw_response,
            record_id  = extra.get("record_id"),
            flags      = extra.get("flags", []),
            math       = extra.get("math"),
            save_error = extra.get("save_error"),
        )

    except Exception as e:
        logger.error(str(e))
        return JobResponse(job_id=job_id, status="failed", error=str(e), run_id=run_id)


@app.post("/cost", response_model=CostResponse)
async def estimate_cost(req: ExecuteRequest):
    """
    Dry-run the circuit on IonQ to get cost + gate count estimate.
    Uses IonQ's dry_run mode — no QPU time consumed.
    """
    circuit_hash = compute_circuit_hash(req.ir_json)
    logger = ArtifactLogger()
    run_id, _ = logger.open_run(circuit_hash)
    try:
        if not logger.has_core_artifacts():
            logger.save("canvas.json", req.canvas_json)
            logger.save("ir.json",     req.ir_json)
            logger.save("qiskit.py",   req.qiskit_py)
        logger.record_run(circuit_hash, "qpu_estimate", req.shots)
        logger.log(f"Dry-run cost estimate for qpu.forte-1 — hash={circuit_hash[:12]}…")

        runner = IonQRunner(
            api_key  = settings.IONQ_API_KEY,
            endpoint = settings.IONQ_ENDPOINT,
            logger   = logger,
        )
        ionq_circuit = None
        if req.concept_ir is not None:
            c = compile_document(req.concept_ir, backend="ionq")
            if not c.ok or c.ionq is None:
                msgs = [e.message for e in c.errors] + [w.message for w in c.warnings if w.code == "W_BACKEND_UNSUPPORTED"]
                return CostResponse(error=" ".join(msgs) or "This circuit can't be lowered for IonQ.")
            ionq_circuit = c.ionq
        cost_info = runner.estimate_cost(req.qiskit_py, req.shots, ionq_circuit=ionq_circuit)
        logger.save("cost_estimate.json", cost_info)
        logger.log(f"Estimate resolved — cost_usd={cost_info.get('cost_usd')} "
                   f"status={cost_info.get('status')}")
        return CostResponse(**cost_info)
    except Exception as e:
        logger.error(str(e))
        return CostResponse(error=str(e))


@app.post("/qasm", response_model=QasmResponse)
async def export_qasm(req: QasmRequest):
    """Export the generated Qiskit circuit as OpenQASM 2.0 text, e.g. for
    pasting into IBM Quantum Composer's code editor."""
    try:
        from qasm_export import export_qasm2
        return QasmResponse(qasm=export_qasm2(req.qiskit_py))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/compile")
async def compile_concepts(req: CompileRequest):
    """Concept IR -> validation messages, pseudocode, Qiskit code, gates + trace, (QASM 3, IonQ gates).
    Deterministic and side-effect free: nothing is logged or executed."""
    if req.document is not None:
        raw = req.document
    else:
        raw = merge_canvas(req.legacy_ir, req.nodes, req.classical_bits)
    res = compile_document(raw, backend=req.backend, with_qasm=req.qasm)
    out = res.to_dict()
    out["document"] = out["document"] or raw
    return out


@app.get("/problems")
async def list_problems():
    return [problem_bank.public_view(p) for p in problem_bank.load_problems()]


@app.post("/check-problem")
async def check_problem(req: CheckProblemRequest):
    p = problem_bank.get_problem(req.problem_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown problem: {req.problem_id}")
    return problem_bank.check_solution(p, req.document)


class ExplainRequest(BaseModel):
    record_id: str | None = None      # explain a stored run (its math log and counts), or...
    document: dict | None = None      # ...a Concept IR (+ counts) that was not run yet
    counts: dict | None = None
    labels: list[str] = []            # canvas qubit names, so the text says Q1/Q2 like the screen does
    use_llm: bool = True


@app.post("/explain")
async def explain_run(req: ExplainRequest):
    """Template explanation (always) + optional grounded LLM explanation that must pass the claim checker.
    The LLM key is read from server-side env vars only. Never returns prompts, keys or provider errors with secrets."""
    from explain.service import explain as do_explain
    from mathlayer import analyze_document
    rec = None
    if req.record_id:
        rec = executor.store().load(req.record_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"No run record {req.record_id}")
        doc, counts = rec["input"].get("ir_migrated") or rec["input"]["ir_json"], rec["results"]["counts"]
        log = rec["results"].get("math_log")
        if not isinstance(doc, dict) or doc.get("operations") is None:
            raise HTTPException(status_code=400, detail="This run has no concept circuit to explain.")
    elif req.document:
        doc, counts, log = req.document, req.counts, None
    else:
        raise HTTPException(status_code=400, detail="Send record_id, or a document.")
    if not log or not log.get("steps"):
        log = analyze_document(doc, results=counts, code_check=False)
    if not log.get("steps"):
        raise HTTPException(status_code=400, detail="This circuit is too large for step-by-step explanations.")
    import time
    t0 = time.perf_counter()
    result = do_explain(log, doc, counts, req.labels, settings, use_llm=req.use_llm)
    log_event("explain", run_id=req.record_id, stage="explain", duration_ms=(time.perf_counter() - t0) * 1000,
              llm_status=(result["llm"] or {}).get("status"), provider=(result["llm"] or {}).get("provider"),
              cache_hit=(result["llm"] or {}).get("cache_hit"))
    save_error = None
    if rec is not None:                                                    # append the explanation to the run (new revision)
        try:
            def upd(r):
                r["explanation"] = {"template": result["template"]["steps"] and [{"summary": result["template"]["summary"], "steps": result["template"]["steps"]}],
                                    "llm": result["llm"]}
                if (result["llm"] or {}).get("status") == "rejected":
                    r["flags"].append({"flag": "llm_claim_check_failed", "detail": "; ".join(v["detail"] for v in result["llm"]["claim_check"]["violations"])[:500]})
            executor.store().append_revision(req.record_id, upd)
        except Exception as e:
            save_error = f"The explanation could not be added to the run record: {e}"
            log_event("record_save_failed", level="error", run_id=req.record_id, stage="save", message=str(e))
    llm_pub = {k: v for k, v in (result["llm"] or {}).items() if k not in ("prompt", "response", "attempts")}
    llm_pub["attempts"] = [{"provider": a.get("provider"), "kind": a.get("kind"), "ok": a.get("ok"), "error": (a.get("error") or "")[:300] or None} for a in (result["llm"] or {}).get("attempts", [])]
    return {"template": result["template"], "llm": llm_pub, "save_error": save_error}


class MathRequest(BaseModel):
    document: dict                    # a Concept IR (what /compile returned as "document")
    labels: list[str] = []


def _checked_doc(doc: dict):
    from mathlayer.layer import normalise_ir
    try:
        return normalise_ir(doc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"This is not a valid concept circuit: {e}")


@app.post("/math")
async def math_steps(req: MathRequest):
    """Per-step maths for the Math tab: exact kets, gate matrices and U.state calculations. Deterministic, no AI."""
    from mathlayer.notation import step_math
    doc = _checked_doc(req.document)
    try:
        return step_math(doc, req.labels or None)
    except Exception as e:
        log_event("math_failed", level="error", stage="math", message=str(e)[:300])
        raise HTTPException(status_code=400, detail="The maths for this circuit could not be worked out exactly.")


class ExplainStepRequest(BaseModel):
    document: dict
    step_id: str
    counts: dict | None = None
    labels: list[str] = []
    use_llm: bool = True


@app.post("/explain-step")
async def explain_one_step(req: ExplainStepRequest):
    """The "?" button: exact maths + template sentence for one step, plus an optional claim-checked AI paragraph."""
    from explain.step import explain_step
    from mathlayer import analyze_document
    from mathlayer.notation import step_math
    doc = _checked_doc(req.document)
    if req.step_id not in {o["id"] for o in doc["operations"]}:
        raise HTTPException(status_code=404, detail=f"No step {req.step_id}")
    labels = req.labels or [f"Q{i + 1}" for i in range(doc["qubits"])]
    log = analyze_document(doc, results=req.counts, code_check=False)
    if not log.get("steps"):
        raise HTTPException(status_code=400, detail="This circuit is too large for step-by-step explanations.")
    sm = next((s for s in step_math(doc, labels)["steps"] if s["id"] == req.step_id), {})
    res = explain_step(log, doc, req.step_id, sm, req.counts, labels, settings, use_llm=req.use_llm)
    L = res["llm"]
    log_event("explain_step", stage="explain", step=req.step_id, llm_status=L.get("status"), provider=L.get("provider"))
    L["attempts"] = [{"provider": a.get("provider"), "kind": a.get("kind"), "ok": a.get("ok"), "error": (a.get("error") or "")[:300] or None} for a in L.get("attempts", [])]
    return res


@app.get("/runs/{run_id}")
async def get_run_record(run_id: str, revision: int | None = None):
    """The stored run record (latest revision unless one is asked for). Secrets were redacted before it was written."""
    rec = executor.store().load(run_id, revision)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"No run record {run_id}")
    return rec


@app.post("/runs/{run_id}/replay")
async def replay_run(run_id: str):
    """Audit: recompile the stored IR and compare with what was recorded."""
    from runlog.replay import replay
    rec = executor.store().load(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"No run record {run_id}")
    return replay(rec)


class ResearchEvent(BaseModel):
    study_id: str
    consent: bool = False
    session: str = ""
    event: str
    data: dict = {}


@app.post("/research/event")
async def research_event(ev: ResearchEvent):
    """Research interaction logging (Paper A). OFF unless RESEARCH_LOGGING=on AND the event carries consent.
    Stored apart from run records, pseudonymous (session id is hashed). Confirm IRB requirements before any study use."""
    import hashlib, json, datetime, re
    from pathlib import Path
    if str(settings.RESEARCH_LOGGING).lower() != "on" or not ev.consent:
        return {"stored": False, "reason": "research logging is off or consent is missing"}
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", ev.study_id):
        raise HTTPException(status_code=400, detail="invalid study id")
    d = Path(settings.LOG_DIR) / "research"
    d.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "study_id": ev.study_id,
           "pid": hashlib.sha256(("qc-study:" + ev.session).encode()).hexdigest()[:16], "event": ev.event[:80], "data": ev.data}
    from runlog import redact
    with open(d / f"{ev.study_id}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(redact(row)) + "\n")
    return {"stored": True}


@app.get("/health")
def health():
    from explain.llm import configured_providers
    return {"status": "ok", "ionq_configured": bool(settings.IONQ_API_KEY),
            "llm_configured": len(configured_providers(settings)),          # how many providers; never the values
            "research_logging": str(settings.RESEARCH_LOGGING).lower() == "on"}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
