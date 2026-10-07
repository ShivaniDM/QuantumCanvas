"""Append-only run record store. Every save is a NEW file (runrecord_<run_id>.v<N>.json); nothing is overwritten.

Large blobs (raw provider responses, transpiled circuits, statevector-sized logs) are stored COMPRESSED next to the
record with a pointer {"$ref", "bytes", "sha256", "encoding"} left in the record; nothing is truncated silently.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import jsonschema

from .redact import redact
from .schema import RUN_RECORD_V2
from .serverlog import log_event

BLOB_LIMIT = 64 * 1024            # bytes of JSON above which a field moves to a compressed sidecar
BLOB_FIELDS = (("execution", "raw_provider_response"), ("execution", "transpiled"), ("results", "math_log"),
               ("compile", "trace"), ("compile", "gates"))


class RecordInvalid(Exception):
    """The record failed schema validation. Never swallowed: callers show this to the user."""


def _validator():
    return jsonschema.Draft202012Validator(RUN_RECORD_V2)


def validate_record(rec: dict) -> None:
    errs = sorted(_validator().iter_errors(rec), key=lambda e: list(e.absolute_path))
    if errs:
        msg = "; ".join(f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in errs[:6])
        raise RecordInvalid(msg)


def _jsonable(x):
    return json.loads(json.dumps(x, default=str))


class RunStore:
    def __init__(self, base_dir):
        self.base = Path(base_dir)

    def _dir(self, rec: dict) -> Path:
        folder = rec["identity"].get("circuit_folder") or "unfiled"
        d = self.base / "runs" / folder
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, rec: dict) -> Path:
        """Redact → externalise big blobs → validate → write a new revision. Raises RecordInvalid / OSError."""
        rec = redact(_jsonable(rec))
        d = self._dir(rec)
        rid, rev = rec["run_id"], rec["revision"]
        rec = self._externalise(rec, d, rid, rev)
        validate_record(rec)
        path = d / f"runrecord_{rid}.v{rev}.json"
        if path.exists():
            raise RecordInvalid(f"{path.name} already exists (records are append-only)")
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        with open(d / "runrecords.index.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": rid, "revision": rev, "status": rec["status"], "file": path.name,
                                "created_at": rec["identity"]["created_at"], "backend_requested": rec["execution"]["backend_requested"],
                                "backend_executed": rec["execution"]["backend_executed"], "flags": [x["flag"] for x in rec["flags"]]}) + "\n")
        log_event("record_saved", run_id=rid, stage="save", revision=rev, file=str(path))
        try:                                                    # mirror (optional, never the only copy)
            import mongo_logger
            if rec["identity"].get("circuit_hash"):
                mongo_logger.mirror_file(rec["identity"]["circuit_hash"], rec["identity"]["circuit_folder"], path.name, rec)
        except Exception as e:                                  # pragma: no cover - mirror is best effort
            log_event("mirror_failed", level="warning", run_id=rid, stage="save", message=str(e))
        return path

    def _externalise(self, rec, d: Path, rid: str, rev: int):
        for group, key in BLOB_FIELDS:
            val = rec.get(group, {}).get(key)
            if val is None:
                continue
            raw = json.dumps(val, ensure_ascii=False).encode("utf-8")
            if len(raw) <= BLOB_LIMIT:
                continue
            name = f"runrecord_{rid}.v{rev}.{group}.{key}.json.gz"
            (d / name).write_bytes(gzip.compress(raw))
            rec[group][key] = {"$ref": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "encoding": "gzip+json"}
        return rec

    def append_revision(self, run_id: str, update) -> dict:
        """Append-only edit of an existing run: load the latest revision, let `update(rec)` change it, save as revision+1."""
        rec = self.load(run_id)
        if rec is None:
            raise RecordInvalid(f"no run record {run_id} to append to")
        rec["revision"] += 1
        update(rec)
        self.save(rec)
        return rec

    # ── reading ───────────────────────────────────────────────────────
    def find(self, run_id: str) -> list[Path]:
        return sorted((self.base / "runs").glob(f"*/runrecord_{run_id}.v*.json"),
                      key=lambda p: int(p.stem.rsplit(".v", 1)[1]))

    def load(self, run_id: str, revision: int | None = None, resolve_blobs=True) -> dict | None:
        files = self.find(run_id)
        if not files:
            return None
        path = files[-1] if revision is None else next((p for p in files if p.stem.endswith(f".v{revision}")), None)
        if path is None:
            return None
        rec = json.loads(path.read_text(encoding="utf-8"))
        if resolve_blobs:
            for group, key in BLOB_FIELDS:
                v = rec.get(group, {}).get(key)
                if isinstance(v, dict) and "$ref" in v:
                    raw = gzip.decompress((path.parent / v["$ref"]).read_bytes())
                    if hashlib.sha256(raw).hexdigest() != v["sha256"]:
                        raise RecordInvalid(f"blob {v['$ref']} fails its checksum")
                    rec[group][key] = json.loads(raw)
        return rec
