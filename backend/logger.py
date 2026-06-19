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
import datetime
from pathlib import Path
from config import settings


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

    def run_path(self) -> str:
        return str(self.run_dir) if self.run_dir else ""
