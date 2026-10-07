"""Structured server logs: one JSON object per line, every line joinable to a run by run_id.

Fields: ts, level, run_id, stage, event, duration_ms, plus anything extra. Written to stdout (Azure captures it)
and to <LOG_DIR>/server.jsonl (git-ignored). Stack traces go HERE only, never to the client.
"""
from __future__ import annotations

import datetime
import json
import sys
import threading
from pathlib import Path

from .redact import redact

_lock = threading.Lock()


def _file() -> Path | None:
    try:
        from config import settings
        p = Path(settings.LOG_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p / "server.jsonl"
    except Exception:
        return None


def log_event(event: str, *, level="info", run_id=None, stage=None, duration_ms=None, **fields):
    line = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"), "level": level,
            "run_id": run_id, "stage": stage, "event": event,
            "duration_ms": None if duration_ms is None else round(float(duration_ms), 1)}
    line.update(fields)
    text = json.dumps(redact(line), default=str, ensure_ascii=False)
    with _lock:
        try:
            print(json.dumps(json.loads(text), default=str, ensure_ascii=True), file=sys.stdout, flush=True)
            f = _file()
            if f is not None:
                with open(f, "a", encoding="utf-8") as fh:
                    fh.write(text + "\n")
        except Exception:                                   # logging must never take the app down
            pass
    return line
