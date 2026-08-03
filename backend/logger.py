"""
QuantumCanvas — Artifact Logger

Every unique circuit gets ONE folder under logs/runs/, keyed by a stable hash
of its IR — not a timestamp. Saving the same circuit again, or running a
different backend against it, reuses that same folder instead of scattering
results across new ones each time:

  logs/runs/
    <circuit_hash>/
      canvas.json
      ir.json
      pseudocode.txt
      qiskit.py
      results_aer.json
      results_ionq.json
      results_qpu.json
      metadata.json        # accumulates one entry per backend that ran
      execution.log
      errors.log
"""

import json
import hashlib
import datetime
import subprocess
from pathlib import Path
from config import settings
import mongo_logger


def compute_circuit_hash(ir_json_str: str) -> str:
    """
    SHA-256 of the canonically serialised IR.
    Canonical = sort_keys=True, no whitespace.
    Hashing the IR (not the Qiskit text) means reformatted code
    still produces the same hash — the circuit is the identity.
    """
    try:
        ir_obj    = json.loads(ir_json_str)
        canonical = json.dumps(ir_obj, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.sha256(ir_json_str.encode("utf-8")).hexdigest()


def get_git_commit() -> str:
    """Return current HEAD SHA, or 'unknown' if not in a git repo."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


class ArtifactLogger:
    def __init__(self, run_id: str | None = None, circuit_hash: str | None = None):
        self.run_id       = run_id
        self.circuit_hash = circuit_hash
        self.run_dir      = None
        if run_id:
            self.run_dir = Path(settings.LOG_DIR) / "runs" / run_id
            self.run_dir.mkdir(parents=True, exist_ok=True)

    def open_run(self, circuit_hash: str) -> tuple[str, bool]:
        """
        Open the folder for this circuit's hash — creating it if this exact
        circuit has never been saved before, reusing it otherwise.
        Returns (run_id, is_new).
        """
        self.circuit_hash = circuit_hash
        self.run_id  = circuit_hash[:12]
        self.run_dir = Path(settings.LOG_DIR) / "runs" / self.run_id
        is_new = not self.run_dir.exists()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"{'Created' if is_new else 'Reusing'} run directory: {self.run_dir}")
        return self.run_id, is_new

    def has_core_artifacts(self) -> bool:
        """True if canvas/IR/pseudocode/qiskit are already saved for this run."""
        return bool(self.run_dir) and (self.run_dir / "ir.json").exists()

    def save(self, filename: str, content: str | dict | list) -> Path:
        """
        Write content to a file inside the run directory, and mirror it into
        MongoDB too (if configured) — every file saved locally lands in the
        Mongo document under files.<filename>, so the two never drift apart.
        """
        if not self.run_dir:
            return None
        path = self.run_dir / filename
        if isinstance(content, (dict, list)):
            path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        else:
            path.write_text(str(content), encoding="utf-8")
        if self.circuit_hash:
            mongo_logger.mirror_file(self.circuit_hash, self.run_id, filename, content)
        return path

    def log(self, message: str) -> None:
        """Append a timestamped line to execution.log."""
        self._write_log("execution.log", message)

    def error(self, message: str) -> None:
        """Append a timestamped line to errors.log and execution.log."""
        self._write_log("errors.log",    f"ERROR: {message}")
        self._write_log("execution.log", f"ERROR: {message}")

    def _write_log(self, filename: str, message: str) -> None:
        if not self.run_dir:
            print(f"[LOG] {message}")
            return
        ts   = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {message}\n"
        path = self.run_dir / filename
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    def record_run(self, circuit_hash: str, backend: str, shots: int) -> None:
        """
        Update metadata.json with an entry for this backend, preserving any
        other backends already recorded for this same circuit (so running
        Aer then IonQ Sim against the same circuit accumulates both, rather
        than the second overwriting the first).
        """
        if not self.run_dir:
            return
        path = self.run_dir / "metadata.json"
        meta = {}
        if path.exists():
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        meta.setdefault("circuit_hash", circuit_hash)
        meta.setdefault("run_id",       self.run_id)
        meta.setdefault("created_at",   datetime.datetime.now().isoformat())
        meta.setdefault("backends",     {})
        meta["backends"][backend] = {
            "shots":      shots,
            "git_commit": get_git_commit(),
            "ran_at":     datetime.datetime.now().isoformat(),
        }
        meta["updated_at"] = datetime.datetime.now().isoformat()
        self.save("metadata.json",    meta)
        self.save("circuit_hash.txt", circuit_hash)
        self.log(f"CIRCUIT_HASH={circuit_hash} BACKEND={backend} SHOTS={shots}")

    def run_path(self) -> str:
        return str(self.run_dir) if self.run_dir else ""
