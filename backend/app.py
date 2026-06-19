"""
QuantumCanvas Backend — FastAPI
Routes:
  POST /execute   — receive canvas artifacts, run simulator or IonQ, save logs
  GET  /job/{id}  — poll IonQ job status
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from config      import settings
from logger      import ArtifactLogger
from ionq_runner import IonQRunner, JobStatus

app = FastAPI(title="QuantumCanvas API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten for production
    allow_methods=["POST","GET"],
    allow_headers=["*"],
)

# ── Request / response models ─────────────────────────────────────────

class ExecuteRequest(BaseModel):
    canvas_json:    str
    ir_json:        str
    pseudocode_txt: str
    qiskit_py:      str
    backend:        str   # "simulator" | "ionq"
    shots:          int   = 1000

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

class CostResponse(BaseModel):
    cost_usd:    float | None = None
    queue_days:  int   | None = None
    target:      str          = "qpu.forte-1"
    gate_counts: dict | None  = None
    error:       str   | None = None

# ── Routes ────────────────────────────────────────────────────────────

@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest):
    logger = ArtifactLogger()
    run_id = logger.new_run(req.backend)

    try:
        # Save all input artifacts immediately
        logger.save("canvas.json",   req.canvas_json)
        logger.save("ir.json",       req.ir_json)
        logger.save("pseudocode.txt",req.pseudocode_txt)
        logger.save("qiskit.py",     req.qiskit_py)

        # Compute circuit hash + git commit; writes metadata.json and circuit_hash.txt
        circuit_hash = logger.save_metadata(req.ir_json, req.backend, req.shots)
        logger.log(f"Run {run_id} started — backend={req.backend} shots={req.shots} hash={circuit_hash[:12]}…")

        runner = IonQRunner(
            api_key    = settings.IONQ_API_KEY,
            endpoint   = settings.IONQ_ENDPOINT,
            logger     = logger,
        )

        if req.backend == "simulator":
            # Synchronous: submit to IonQ cloud simulator, poll until done
            counts = runner.run_simulator(
                qiskit_code = req.qiskit_py,
                shots       = req.shots,
            )
            # Save results.json with hash for traceability; return clean counts to frontend
            results_artifact = dict(counts)
            results_artifact["circuit_hash"] = circuit_hash
            logger.save("results.json", results_artifact)
            logger.log(f"Simulator complete — {sum(counts.values())} shots")
            return ExecuteResponse(run_id=run_id, counts=counts)   # no hash key in response

        elif req.backend == "ionq":
            # Async: submit to IonQ, return job_id for polling
            job_id = runner.submit_hardware(
                qiskit_code = req.qiskit_py,
                shots       = req.shots,
            )
            logger.log(f"IonQ job submitted — job_id={job_id}")
            # Store run_id → job_id mapping for the poll endpoint
            _job_run_map[job_id] = run_id
            return ExecuteResponse(run_id=run_id, job_id=job_id)

        elif req.backend == "qpu":
            # User confirmed QPU run after seeing cost estimate
            job_id = runner.submit_qpu(
                qiskit_code = req.qiskit_py,
                shots       = req.shots,
            )
            logger.log(f"QPU job submitted — job_id={job_id}")
            _job_run_map[job_id] = run_id
            return ExecuteResponse(run_id=run_id, job_id=job_id)

        else:
            raise HTTPException(status_code=400, detail=f"Unknown backend: {req.backend}")

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(status_code=500, detail=str(e))


# In-memory job→run mapping (production: use a DB or Redis)
_job_run_map: dict[str, str] = {}

@app.get("/job/{job_id}", response_model=JobResponse)
async def poll_job(job_id: str):
    run_id = _job_run_map.get(job_id)
    logger = ArtifactLogger(run_id=run_id) if run_id else ArtifactLogger()

    try:
        runner = IonQRunner(
            api_key  = settings.IONQ_API_KEY,
            endpoint = settings.IONQ_ENDPOINT,
            logger   = logger,
        )
        status: JobStatus = runner.get_job_status(job_id)

        if status.is_terminal and status.counts:
            logger.save("ionq_response.json", status.raw_response)
            logger.save("results.json",       status.counts)
            logger.log(f"Job {job_id} completed — saving artifacts")

        return JobResponse(
            job_id = job_id,
            status = status.status,
            counts = status.counts,
            run_id = run_id,
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
    logger = ArtifactLogger()
    try:
        runner = IonQRunner(
            api_key  = settings.IONQ_API_KEY,
            endpoint = settings.IONQ_ENDPOINT,
            logger   = logger,
        )
        cost_info = runner.estimate_cost(req.qiskit_py, req.shots)
        return CostResponse(**cost_info)
    except Exception as e:
        return CostResponse(error=str(e))


@app.get("/health")
def health():
    return {"status": "ok", "ionq_configured": bool(settings.IONQ_API_KEY)}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
