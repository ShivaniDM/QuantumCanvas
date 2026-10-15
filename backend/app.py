from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Literal
import random
import json
import uvicorn

from config      import settings
from logger      import ArtifactLogger, compute_circuit_hash
from ionq_runner import IonQRunner, JobStatus
from concepts    import compile_document
from concepts.migrate import merge_canvas
from ratelimit   import RateLimitMiddleware
import problems as problem_bank
import executor
from runlog import log_event

app = FastAPI(title="QuantumCanvas API", version="1.0.0")

_cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"]
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


def _check_circuit_size(n_qubits: int | None, shots: int | None = None):
    if n_qubits is not None and n_qubits > settings.MAX_QUBITS:
        raise HTTPException(status_code=400,
                            detail=f"This circuit has {n_qubits} qubits; the server limit is {settings.MAX_QUBITS}.")
    if shots is not None and shots > settings.MAX_SHOTS:
        raise HTTPException(status_code=400,
                            detail=f"{shots} shots exceeds the server limit of {settings.MAX_SHOTS}.")


def _n_qubits_of(concept_ir: dict | None, ir_json) -> int | None:
    if isinstance(concept_ir, dict) and isinstance(concept_ir.get("qubits"), int):
        return concept_ir["qubits"]
    try:
        obj = json.loads(ir_json) if isinstance(ir_json, str) else ir_json
    except Exception:
        return None
    if isinstance(obj, dict):
        if isinstance(obj.get("qubits"), int):
            return obj["qubits"]
        if isinstance(obj.get("qubits"), list):
            return len(obj["qubits"])
    return None


class LogCircuitRequest(BaseModel):
    canvas_json:    str
    ir_json:        str
    pseudocode_txt: str = ""
    qiskit_py:      str = ""

class LogCircuitResponse(BaseModel):
    ok:            bool
    circuit_hash:  str
    run_id:        str
    path:          str
    files:         list[str] = []
    already_saved: bool

class ExecuteRequest(BaseModel):
    canvas_json:    str
    ir_json:        str
    pseudocode_txt: str
    qiskit_py:      str
    backend:        str
    optimization_level: int = Field(1, ge=0, le=3)
    gateset:        Literal["qis", "native"] = "qis"
    seed:           int | None = Field(None, ge=0, lt=2 ** 31)
    shots:          int   = 1000
    session_id:     str | None = None
    user:           str | None = None
    parent_run_id:  str | None = None
    concept_ir:     dict | None = None

class ExecuteResponse(BaseModel):
    run_id:   str
    record_id: str | None = None
    counts:   dict | None = None
    job_id:   str | None  = None
    status:   str = "ok"
    flags:    list = []
    math:     dict | None = None
    save_error: str | None = None
    compile_report: dict | None = None

class JobResponse(BaseModel):
    job_id:  str
    status:  str
    counts:  dict | None = None
    run_id:  str | None  = None
    error:   str | None  = None
    raw:     dict | None = None
    record_id: str | None = None
    flags:   list = []
    math:    dict | None = None
    save_error: str | None = None

class CompileRequest(BaseModel):
    document:       dict | None = None
    legacy_ir:      dict | None = None
    nodes:          list[dict] = []
    classical_bits: int = 0
    backend:        str | None = None
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
    gate_counts:               Any          = None
    predicted_execution_time:  float | None = None
    status:                    str   | None = None
    raw:                       dict  | None = None
    error:                     str   | None = None
    compile_report:            dict  | None = None

class TranspileRequest(BaseModel):
    qiskit_py:      str = ""
    concept_ir:     dict | None = None
    backend:        str
    optimization_level: int = Field(1, ge=0, le=3)
    gateset:        Literal["qis", "native"] = "qis"
    seed:           int | None = Field(None, ge=0, lt=2 ** 31)
    shots:          int = Field(1000, ge=1)


@app.post("/log-circuit", response_model=LogCircuitResponse)
async def log_circuit(req: LogCircuitRequest):
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


def _spec_or_400(backend: str):
    from engine_bridge import bridge
    from engine_bridge.client import EngineUnavailable
    try:
        return bridge.get(backend)
    except bridge.UnknownBackend as e:
        raise HTTPException(status_code=400, detail=str(e.args[0]))
    except EngineUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


def _check_qpu_allowed(backend: str):
    hardware = backend == "qpu" or (backend not in ("aer", "simulator", "ionq")
                                    and _spec_or_400(backend).group == "hardware")
    if hardware and str(settings.ALLOW_QPU_SUBMIT).lower() != "on":
        raise HTTPException(status_code=403,
                            detail="Submitting to real quantum hardware is disabled on this server.")


def _check_target_size(backend: str, n_qubits: int | None, shots: int | None):
    if backend in ("aer", "simulator", "ionq", "qpu"):
        _check_circuit_size(n_qubits, shots)
        return
    spec = _spec_or_400(backend)
    if spec.provider == "ionq":
        _check_circuit_size(None, shots)
        if n_qubits is not None and n_qubits > spec.qubits:
            raise HTTPException(status_code=400, detail=f"{spec.label} has {spec.qubits} qubits; "
                                                        f"this circuit needs {n_qubits}.")
    else:
        _check_circuit_size(n_qubits, shots)


LEGACY_IONQ_SIMULATOR = ("simulator", "ionq")


def _check_offered(backend: str) -> None:
    from engine_bridge import bridge
    if backend not in bridge.OFFERED and backend not in LEGACY_IONQ_SIMULATOR:
        raise HTTPException(status_code=400, detail=f"The backend {backend!r} isn't offered here. "
                                                    "Use the built-in simulator or an IonQ simulator.")


@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest):
    _check_offered(req.backend)
    _check_qpu_allowed(req.backend)
    _check_target_size(req.backend, _n_qubits_of(req.concept_ir, req.ir_json), req.shots)
    if req.backend not in ("aer", "simulator", "ionq", "qpu"):
        from engine_bridge.bridge import availability
        why = availability(_spec_or_400(req.backend), settings)
        if why:
            raise HTTPException(status_code=503, detail=why)
    body = req.model_dump()
    if body.get("seed") is None:
        body["seed"] = random.SystemRandom().randrange(2 ** 31)
    return ExecuteResponse(**executor.execute(body))


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
        requested_shots = ((live or {}).get("req") or {}).get("shots")
        status: JobStatus = runner.get_job_status(job_id, backend_label=backend, shots=requested_shots)

        if status.is_terminal and status.counts:
            logger.save(f"ionq_completed_{backend}.json", status.raw_response)
            logger.save(f"results_{backend}.json",        status.counts)
            logger.log(f"Job {job_id} completed — saving artifacts")

        extra = executor.on_job_status(job_id, status)
        return JobResponse(
            job_id = job_id,
            status = status.status,
            counts = extra.get("counts", status.counts),
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
    _check_circuit_size(_n_qubits_of(req.concept_ir, req.ir_json), req.shots)
    circuit_hash = compute_circuit_hash(req.ir_json)
    logger = ArtifactLogger()
    run_id, _ = logger.open_run(circuit_hash)
    try:
        if not logger.has_core_artifacts():
            logger.save("canvas.json", req.canvas_json)
            logger.save("ir.json",     req.ir_json)
            logger.save("qiskit.py",   req.qiskit_py)
        logger.record_run(circuit_hash, "qpu_estimate", req.shots)
        logger.log(f"Dry-run cost estimate for {req.backend} — hash={circuit_hash[:12]}…")

        runner = IonQRunner(
            api_key  = settings.IONQ_API_KEY,
            endpoint = settings.IONQ_ENDPOINT,
            logger   = logger,
        )
        ionq_circuit = None
        spec = _spec_or_400(req.backend) if req.backend not in ("qpu", "aer", "simulator", "ionq") else None
        report = None
        if spec is not None and spec.group == "hardware":
            from engine_bridge.bridge import SourceError, compile_request, offline_ionq
            from engine_bridge.client import EngineRequestError, EngineUnavailable
            body = {**req.model_dump(), "seed": req.seed or 1234}
            try:
                try:
                    compiled = compile_request(body, spec.id)
                except EngineUnavailable:
                    compiled = offline_ionq(body, spec)
            except (SourceError, EngineRequestError) as e:
                return CostResponse(error=str(e))
            report = compiled.report
            if not compiled.ok:
                return CostResponse(error=" ".join(report["blocking"]), compile_report=report)
            ionq_circuit = compiled.payload
        elif req.concept_ir is not None:
            c = compile_document(req.concept_ir, backend="ionq")
            if not c.ok or c.ionq is None:
                msgs = [e.message for e in c.errors] + [w.message for w in c.warnings if w.code == "W_BACKEND_UNSUPPORTED"]
                return CostResponse(error=" ".join(msgs) or "This circuit can't be lowered for IonQ.")
            ionq_circuit = c.ionq
        qpu_name = spec.device if spec is not None and spec.group == "hardware" else "qpu.forte-1"
        cost_info = runner.estimate_cost(req.qiskit_py, req.shots, ionq_circuit=ionq_circuit, backend=qpu_name)
        cost_info["compile_report"] = report
        logger.save("cost_estimate.json", cost_info)
        logger.log(f"Estimate resolved — cost_usd={cost_info.get('cost_usd')} "
                   f"status={cost_info.get('status')}")
        return CostResponse(**cost_info)
    except Exception as e:
        logger.error(str(e))
        return CostResponse(error=str(e))


@app.post("/qasm", response_model=QasmResponse)
async def export_qasm(req: QasmRequest):
    try:
        from qasm_export import export_qasm2
        return QasmResponse(qasm=export_qasm2(req.qiskit_py))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_event("qasm_export_failed", level="error", message=str(e)[:500])
        raise HTTPException(status_code=500, detail="QASM export failed unexpectedly.")


@app.post("/compile")
async def compile_concepts(req: CompileRequest):
    if req.document is not None:
        raw = req.document
    else:
        raw = merge_canvas(req.legacy_ir, req.nodes, req.classical_bits)
    _check_circuit_size(raw.get("qubits") if isinstance(raw, dict) else None)
    res = compile_document(raw, backend=req.backend, with_qasm=req.qasm)
    out = res.to_dict()
    out["document"] = out["document"] or raw
    return out


@app.get("/backends")
async def list_backends():
    from engine_bridge.bridge import listing
    return listing(settings)


@app.get("/backends/{backend_id}")
async def backend_details(backend_id: str):
    from engine_bridge.bridge import details
    return details(_spec_or_400(backend_id), settings)


@app.post("/transpile")
async def transpile_for_backend(req: TranspileRequest):
    from engine_bridge.bridge import SourceError, compile_request, offline_ionq
    from engine_bridge.client import EngineRequestError, EngineUnavailable
    spec = _spec_or_400(req.backend)
    n = req.concept_ir.get("qubits") if isinstance(req.concept_ir, dict) else None
    if spec.provider == "ionq":
        if isinstance(n, int) and n > spec.qubits:
            raise HTTPException(status_code=400, detail=f"{spec.label} has {spec.qubits} qubits; this circuit needs {n}.")
    else:
        _check_circuit_size(n if isinstance(n, int) else None)
    body = req.model_dump()
    if body.get("seed") is None:
        body["seed"] = random.SystemRandom().randrange(2 ** 31)
    try:
        try:
            return compile_request(body, spec.id).report
        except EngineUnavailable as e:
            if spec.provider != "ionq":
                raise HTTPException(status_code=503, detail=str(e))
            return offline_ionq(body, spec).report
    except (SourceError, EngineRequestError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/problems")
async def list_problems():
    return [problem_bank.public_view(p) for p in problem_bank.load_problems()]


@app.post("/check-problem")
async def check_problem(req: CheckProblemRequest):
    p = problem_bank.get_problem(req.problem_id)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown problem: {req.problem_id}")
    return problem_bank.check_solution(p, req.document)


class ImportRequest(BaseModel):
    format: Literal["qasm3", "qasm2", "qiskit"]
    source: str


@app.post("/import")
async def import_code(req: ImportRequest):
    from codeimport import ImportFailed, import_source
    try:
        return import_source(req.format, req.source, settings.MAX_QUBITS)
    except ImportFailed as e:
        return {"ok": False, "error": str(e), "unsupported": e.unsupported, "document": None, "suggestions": []}


class CodeHelpRequest(BaseModel):
    format: Literal["qasm3", "qasm2", "qiskit"]
    source: str = Field(max_length=200_000)
    error: str = Field(default="", max_length=4000)


@app.post("/code-help")
async def code_help(req: CodeHelpRequest):
    from explain.codehelp import code_help as do_help
    res = do_help(req.format, req.source, req.error, settings)
    log_event("code_help", stage="explain", llm_status=res.get("status"), provider=res.get("provider"),
              fix_ok=(res.get("fix_check") or {}).get("ok"))
    return res


class ExplainRequest(BaseModel):
    record_id: str | None = None
    document: dict | None = None
    counts: dict | None = None
    labels: list[str] = []
    use_llm: bool = True


@app.post("/explain")
async def explain_run(req: ExplainRequest):
    from explain.service import explain as do_explain
    from mathlayer import analyze_document
    rec = None
    if req.record_id:
        rec = executor.store().load(req.record_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"No run record {req.record_id}")
        doc, counts = rec["input"].get("ir_migrated") or rec["input"]["ir_json"], rec["results"]["counts"]
        log = rec["results"].get("math_log")
        if isinstance(doc, dict) and doc.get("operations") is None:
            doc = executor._legacy_ir_doc({"ir_json": json.dumps(doc)})
            log = None
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
    if rec is not None:
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
    document: dict
    labels: list[str] = []


def _checked_doc(doc: dict):
    from mathlayer.layer import normalise_ir
    try:
        return normalise_ir(doc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"This is not a valid concept circuit: {e}")


@app.post("/math")
async def math_steps(req: MathRequest):
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
    from explain.step import explain_step
    from mathlayer import analyze_document
    from mathlayer.notation import step_math
    doc = _checked_doc(req.document)
    if req.step_id not in {o["id"] for o in doc["operations"]}:
        raise HTTPException(status_code=404, detail=f"No step {req.step_id}")
    labels = req.labels or [f"q{i}" for i in range(doc["qubits"])]
    log = analyze_document(doc, results=req.counts, code_check=False)
    if not log.get("steps"):
        raise HTTPException(status_code=400, detail="This circuit is too large for step-by-step explanations.")
    sm = next((s for s in step_math(doc, labels)["steps"] if s["id"] == req.step_id), {})
    res = explain_step(log, doc, req.step_id, sm, req.counts, labels, settings, use_llm=req.use_llm)
    L = res["llm"]
    log_event("explain_step", stage="explain", step=req.step_id, llm_status=L.get("status"), provider=L.get("provider"))
    L["attempts"] = [{"provider": a.get("provider"), "kind": a.get("kind"), "ok": a.get("ok"), "error": (a.get("error") or "")[:300] or None} for a in L.get("attempts", [])]
    return res


def _checked_run_id(run_id: str) -> str:
    from runlog.store import is_valid_run_id
    if not is_valid_run_id(run_id):
        raise HTTPException(status_code=400, detail="run_id must be exactly 12 lowercase hex characters")
    return run_id


@app.get("/runs/{run_id}")
async def get_run_record(run_id: str, revision: int | None = None):
    rec = executor.store().load(_checked_run_id(run_id), revision)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"No run record {run_id}")
    return rec


@app.post("/runs/{run_id}/replay")
async def replay_run(run_id: str):
    from runlog.replay import replay
    rec = executor.store().load(_checked_run_id(run_id))
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
            "qpu_enabled": bool(settings.IONQ_API_KEY) and str(settings.ALLOW_QPU_SUBMIT).lower() == "on",
            "llm_configured": len(configured_providers(settings)),
            "research_logging": str(settings.RESEARCH_LOGGING).lower() == "on"}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
