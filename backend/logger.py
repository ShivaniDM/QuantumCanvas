"""
QuantumCanvas — Artifact Logger
Every run gets its own timestamped folder under logs/:

  logs/
    2026-06-16_22-41_RUN001/
      canvas.json
      ir.json
      pseudocode.txt
      qiskit.py
      ionq_request.json
      ionq_response.json
      results.json
      execution.log
      errors.log
"""

import os
import json
import hashlib
import datetime
import subprocess
from pathlib import Path
from config import settings


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
    def __init__(self, run_id: str | None = None):
        self.run_id  = run_id
        self.run_dir = None
        if run_id:
            self.run_dir = Path(settings.LOG_DIR) / run_id
            self.run_dir.mkdir(parents=True, exist_ok=True)

    def new_run(self, backend: str) -> str:
        """Create a new timestamped run directory and return its ID."""
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.run_id  = f"{ts}_{backend.upper()}"
        self.run_dir = Path(settings.LOG_DIR) / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"Run directory created: {self.run_dir}")
        return self.run_id

    def save(self, filename: str, content: str | dict | list) -> Path:
        """Write content to a file inside the run directory."""
        if not self.run_dir:
            return None
        path = self.run_dir / filename
        if isinstance(content, (dict, list)):
            path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        else:
            path.write_text(str(content), encoding="utf-8")
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

    def save_metadata(self, ir_json_str: str, backend: str, shots: int) -> str:
        """
        Compute circuit hash + git commit, write metadata.json and circuit_hash.txt,
        stamp execution.log.  Returns the hash string.
        """
        circuit_hash = compute_circuit_hash(ir_json_str)
        git_commit   = get_git_commit()
        ts           = datetime.datetime.now().isoformat()

        metadata = {
            "circuit_hash": circuit_hash,
            "git_commit":   git_commit,
            "backend":      backend,
            "shots":        shots,
            "timestamp":    ts,
            "run_id":       self.run_id,
        }

        self.save("metadata.json",    metadata)
        self.save("circuit_hash.txt", circuit_hash)
        self.log(f"CIRCUIT_HASH={circuit_hash}")
        self.log(f"GIT_COMMIT={git_commit}")
        return circuit_hash

    def run_path(self) -> str:
        return str(self.run_dir) if self.run_dir else ""
