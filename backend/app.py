"""
QuantumCanvas Backend — FastAPI
Routes:
  POST /log-circuit — explicit "save current state" snapshot (no execution)
  POST /execute      — receive canvas artifacts, run simulator or IonQ, save logs
  GET  /job/{id}     — poll IonQ job status
  POST /cost         — dry-run cost estimate for QPU hardware
  POST /qasm         — export generated Qiskit as OpenQASM 2.0 text
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
    # Optional Concept IR v0.3 document. When present the circuit is compiled from it
    # (no exec() of source text, IonQ gates come straight from the compiler) and
    # qiskit_py is only archived.
    concept_ir:     dict | None = None

class ExecuteResponse(BaseModel):
    run_id:   str
    counts:   dict | None = None   # synchronous result (simulator)
    job_id:   str | None  = None   # async job ID (IonQ hardware)
    status:   str = "ok"

class JobResponse(BaseModel):
    job_id:  str
    status:  str   # submitted | running | completed | failed | canceled
    counts:  dict | None = None
    run_id:  str | None  = None
    error:   str | None  = None
    raw:     dict | None = None   # full IonQ job object (hardware metadata)

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
    circuit_hash = compute_circuit_hash(req.ir_json)
    logger = ArtifactLogger()
    run_id, _ = logger.open_run(circuit_hash)

    try:
        # Save input artifacts only if this circuit hasn't been saved yet —
        # avoids clobbering with identical content on repeat runs.
        if not logger.has_core_artifacts():
            logger.save("canvas.json",    req.canvas_json)
            logger.save("ir.json",        req.ir_json)
            logger.save("pseudocode.txt", req.pseudocode_txt)
            logger.save("qiskit.py",      req.qiskit_py)

        logger.record_run(circuit_hash, req.backend, req.shots)
        logger.log(f"Run started — backend={req.backend} shots={req.shots} hash={circuit_hash[:12]}…")

        results_file = f"results_{req.backend}.json"

        concept = None
        if req.concept_ir is not None:
            concept = compile_document(req.concept_ir,
                                       backend="ionq" if req.backend in ("simulator", "ionq", "qpu") else None)
            if not concept.ok:
                raise HTTPException(status_code=400, detail="; ".join(e.message for e in concept.errors))
            logger.save("concept_ir.json", req.concept_ir)
            logger.log(f"Compiled Concept IR — {len(concept.gates)} gates")
            if req.backend in ("simulator", "ionq", "qpu") and concept.ionq is None:
                raise HTTPException(status_code=400, detail=" ".join(
                    w.message for w in concept.warnings if w.code == "W_BACKEND_UNSUPPORTED")
                    or "This circuit can't be lowered for IonQ.")
        ionq_circuit = concept.ionq if concept else None

        # Local Qiskit Aer simulator — runs the generated circuit in-process
        # and returns an exact histogram synchronously. No IonQ / API key needed.
        if req.backend == "aer":
            from aer_runner import run_aer, run_aer_circuit
            if concept:
                from concepts.emit_qiskit import build_circuit
                counts = run_aer_circuit(build_circuit(concept.lowered), req.shots, logger=logger)
            else:
                counts = run_aer(req.qiskit_py, req.shots, logger=logger)
            results_artifact = dict(counts)
            results_artifact["circuit_hash"] = circuit_hash
            logger.save(results_file, results_artifact)
            logger.log(f"Aer simulator complete — {sum(counts.values())} shots")
            return ExecuteResponse(run_id=run_id, counts=counts)

        runner = IonQRunner(
            api_key    = settings.IONQ_API_KEY,
            endpoint   = settings.IONQ_ENDPOINT,
            logger     = logger,
        )

        if req.backend == "simulator":
            # Synchronous: submit to IonQ cloud simulator, poll until done
            counts = runner.run_simulator(
                qiskit_code  = req.qiskit_py,
                shots        = req.shots,
                ionq_circuit = ionq_circuit,
            )
            results_artifact = dict(counts)
            results_artifact["circuit_hash"] = circuit_hash
            logger.save(results_file, results_artifact)
            logger.log(f"Simulator complete — {sum(counts.values())} shots")
            return ExecuteResponse(run_id=run_id, counts=counts)

        elif req.backend == "ionq":
            # Async: submit to the IonQ cloud simulator, return job_id for polling
            job_id = runner.submit_ionq_sim(
                qiskit_code  = req.qiskit_py,
                shots        = req.shots,
                ionq_circuit = ionq_circuit,
            )
            logger.log(f"IonQ job submitted — job_id={job_id}")
            _job_run_map[job_id] = {"run_id": run_id, "backend": req.backend, "circuit_hash": circuit_hash}
            return ExecuteResponse(run_id=run_id, job_id=job_id)

        elif req.backend == "qpu":
            # User confirmed QPU run after seeing cost estimate
            job_id = runner.submit_qpu(
                qiskit_code  = req.qiskit_py,
                shots        = req.shots,
                ionq_circuit = ionq_circuit,
            )
            logger.log(f"QPU job submitted — job_id={job_id}")
            _job_run_map[job_id] = {"run_id": run_id, "backend": req.backend, "circuit_hash": circuit_hash}
            return ExecuteResponse(run_id=run_id, job_id=job_id)

        else:
            raise HTTPException(status_code=400, detail=f"Unknown backend: {req.backend}")

    except HTTPException:
        raise                      # keep deliberate 4xx responses (e.g. invalid concept circuit)
    except Exception as e:
        logger.error(str(e))
        raise HTTPException(status_code=500, detail=str(e))


# In-memory job→run mapping (production: use a DB or Redis)
_job_run_map: dict[str, dict] = {}

@app.get("/job/{job_id}", response_model=JobResponse)
async def poll_job(job_id: str):
    entry        = _job_run_map.get(job_id) or {}
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

        return JobResponse(
            job_id = job_id,
            status = status.status,
            counts = status.counts,
            run_id = run_id,
            raw    = status.raw_response,
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


@app.get("/health")
def health():
    return {"status": "ok", "ionq_configured": bool(settings.IONQ_API_KEY)}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
