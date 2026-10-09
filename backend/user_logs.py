"""
QuantumCanvas — User-attributed log saver (Option C)

Writes a completed run's artifacts into  logs/<username>/<run_id>/  so they can
be committed to the GitHub repo and shared. There is NO GitHub login, OAuth, or
token involved — the username is only a folder-naming convention.

When the backend runs from a local clone (LOG_DIR = ../logs), these files land
directly inside the repo's logs/ folder, ready for:

    git add logs/ && git commit -m "..." && git push
"""

import re
import json
import datetime
from pathlib import Path

from config import settings

# Folder-safe usernames: lower-case, only [a-z0-9_.-], trimmed to 40 chars.
_UNSAFE = re.compile(r"[^a-z0-9_.-]+")


def sanitise_username(name: str, fallback: str = "anonymous") -> str:
    """Turn any user-supplied string into a safe folder name."""
    cleaned = _UNSAFE.sub("-", (name or "").strip().lower()).strip("-.")
    return cleaned[:40] or fallback


def _coerce(content) -> str:
    """Serialise dict/list to pretty JSON; pass strings through unchanged."""
    if isinstance(content, (dict, list)):
        return json.dumps(content, indent=2)
    return "" if content is None else str(content)


def save_user_run(
    username: str,
    *,
    canvas_json: str = "",
    ir_json: str = "",
    pseudocode_txt: str = "",
    qiskit_py: str = "",
    results=None,
    backend: str = "unknown",
    shots: int = 0,
    run_id: str | None = None,
    record: dict | None = None,
) -> dict:
    """
    Persist a run under logs/<username>/<run_id>/ and return a small summary.

    `record` (if given) is the full self-describing run object from the frontend;
    it is written verbatim as run.json for reproducibility.
    """
    user = sanitise_username(username)

    if not run_id:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_id = f"{ts}_{(backend or 'RUN').upper()}"

    run_dir = Path(settings.LOG_DIR) / user / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Individual artifacts — only written when non-empty so we never leave
    # confusing empty files behind.
    artifacts = {
        "canvas.json":    canvas_json,
        "ir.json":        ir_json,
        "pseudocode.txt": pseudocode_txt,
        "qiskit.py":      qiskit_py,
    }
    written = []
    for filename, content in artifacts.items():
        text = _coerce(content)
        if text.strip():
            (run_dir / filename).write_text(text, encoding="utf-8")
            written.append(filename)

    if results is not None:
        (run_dir / "results.json").write_text(_coerce(results), encoding="utf-8")
        written.append("results.json")

    # Full record — the single source of truth for the run.
    full = record or {
        "schema":     "quantumcanvas.run/v1",
        "username":   user,
        "run_id":     run_id,
        "backend":    backend,
        "shots":      shots,
        "results":    results,
        "saved_at":   datetime.datetime.now().isoformat(),
    }
    full = dict(full)
    full["username"] = user
    full["run_id"] = run_id
    full["saved_at"] = datetime.datetime.now().isoformat()
    (run_dir / "run.json").write_text(_coerce(full), encoding="utf-8")
    written.append("run.json")

    # Path relative to the repo root (LOG_DIR is ../logs), for a friendly message.
    rel = f"logs/{user}/{run_id}"

    return {
        "ok":       True,
        "username": user,
        "run_id":   run_id,
        "path":     rel,
        "abs_path": str(run_dir),
        "files":    written,
    }
