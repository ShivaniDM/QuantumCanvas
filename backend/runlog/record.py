"""RunRecorder: collects everything about ONE execution, stage by stage, then produces the v2 record."""
from __future__ import annotations

import contextlib
import datetime
import time
import traceback
import uuid

from . import versions
from .serverlog import log_event

STAGES = ("validate", "compile", "submit", "fetch", "math", "explain", "save")
# what each requested backend is EXPECTED to execute on (provider's own answer is compared against this)
EXPECTED_EXECUTOR = {"aer": "aer_simulator", "simulator": "simulator", "ionq": "simulator", "qpu": "qpu.forte-1"}


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def executor_matches(requested: str, executed: str | None) -> bool:
    """True when the provider says it ran what we asked for. The executed name comes from the PROVIDER'S response."""
    if executed is None:
        return False
    want = EXPECTED_EXECUTOR.get(requested, requested)
    ex = str(executed).lower()
    if requested == "aer":
        return "aer" in ex
    if requested == "qpu":
        return ex.startswith("qpu")
    return ex == want.lower() or (requested in ("simulator", "ionq") and "simulator" in ex)


class RunRecorder:
    def __init__(self, *, backend_requested: str, shots: int | None = None, session_id=None, user="anonymous",
                 parent_run_id=None, run_id=None):
        self.run_id = run_id or new_run_id()
        self.revision = 0
        self.status = "running"
        self.created_at = _now()
        self.finished_at = None
        self.identity = {"session_id": session_id, "user": user or "anonymous", "created_at": self.created_at,
                         "finished_at": None, "parent_run_id": parent_run_id, "circuit_hash": None, "circuit_folder": None}
        self.input = {"canvas_json": None, "ir_json": None, "validator_errors": [], "validator_warnings": [],
                      "pseudocode_txt": None}
        self.compile = {"ir_hash": None, "gates": None, "trace": None, "qiskit_py": None, "qiskit_py_displayed": None,
                        "qasm3": None, "pseudocode": None, "ionq_circuit": None}
        self.execution = {"backend_requested": backend_requested, "backend_executed": None, "provider_job_id": None,
                          "provider_status": None, "shots": shots, "seed": None, "transpiled": None, "timing": {},
                          "cost": None, "raw_provider_response": None}
        self.results = {"counts": None, "math_log": None, "result_check": None}
        self.explanation = {"template": None, "llm": None}
        self.errors: list = []
        self.flags: list = []
        self.edit_history: list = []
        self.timings: dict = {}
        self._t0 = time.perf_counter()

    # ── stages ────────────────────────────────────────────────────────
    @contextlib.contextmanager
    def stage(self, name: str):
        assert name in STAGES, name
        t0 = time.perf_counter()
        log_event("stage_start", run_id=self.run_id, stage=name)
        try:
            yield
        except Exception as e:                                   # record, log the trace server-side, re-raise
            self.error(name, type(e).__name__, str(e), exc=e)
            raise
        finally:
            ms = (time.perf_counter() - t0) * 1000
            self.timings[name] = round(ms, 1)
            log_event("stage_end", run_id=self.run_id, stage=name, duration_ms=ms)

    FATAL_STAGES = ("validate", "compile", "submit", "fetch")

    def error(self, stage: str, code: str, message: str, exc: BaseException | None = None, fatal: bool | None = None):
        """Record an error. A failure in math / explain / save does not turn a finished run into a failed one."""
        self.errors.append({"stage": stage, "code": str(code), "message": str(message)[:2000]})
        log_event("error", level="error", run_id=self.run_id, stage=stage, code=str(code), message=str(message)[:2000],
                  trace=("".join(traceback.format_exception(exc)) if exc else None))
        if (stage in self.FATAL_STAGES) if fatal is None else fatal:
            self.status = "error"

    def flag(self, flag: str, detail: str):
        if not any(f["flag"] == flag and f["detail"] == detail for f in self.flags):
            self.flags.append({"flag": flag, "detail": detail})
            log_event("flag", level="warning", run_id=self.run_id, flag=flag, detail=detail)

    def check_executor(self):
        """Compare the backend that ACTUALLY ran (provider's response) with the one requested."""
        req, ex = self.execution["backend_requested"], self.execution["backend_executed"]
        if ex is None:
            if self.execution.get("provider_job_id") or self.status == "ok":
                self.flag("backend_executed_unknown", f"requested {req!r} but the provider response names no backend")
        elif not executor_matches(req, ex):
            self.flag("backend_mismatch", f"requested {req!r} but the provider executed {ex!r}")

    # ── output ────────────────────────────────────────────────────────
    def finish(self, status: str | None = None):
        self.finished_at = _now()
        self.identity["finished_at"] = self.finished_at
        if status:
            self.status = status
        elif self.status == "running":
            self.status = "ok"

    def to_record(self) -> dict:
        self.revision += 1
        self.execution["timing"] = {**self.timings, **(self.execution.get("timing") or {}),
                                    "total_ms": round((time.perf_counter() - self._t0) * 1000, 1)}
        return {
            "schema": versions.RECORD_SCHEMA, "run_id": self.run_id, "revision": self.revision, "status": self.status,
            "identity": self.identity, "versions": versions.collect(), "input": self.input, "compile": self.compile,
            "execution": self.execution, "results": self.results, "explanation": self.explanation,
            "errors": self.errors, "flags": self.flags, "edit_history": self.edit_history,
        }
