"""
QuantumCanvas — MongoDB Atlas mirror (optional)

If MONGODB_URI is set in .env, every file the local ArtifactLogger writes is
ALSO mirrored into a MongoDB Atlas collection, one document per circuit_hash
— so runs persist even when this backend's local disk is ephemeral (e.g.
hosted on Azure, where logs/runs/ gets wiped on redeploy).

If MONGODB_URI is blank, or the connection fails for any reason, mirror_file
is a silent no-op. Local file logging (logger.py) always happens regardless
— this is a mirror, never the only copy.
"""

from typing import Any
from config import settings

_client = None
_collection = None
_tried = False


def _get_collection():
    """Lazily connect on first use; cache the result (including failures)."""
    global _client, _collection, _tried
    if _tried:
        return _collection
    _tried = True
    if not settings.MONGODB_URI:
        return None
    try:
        from pymongo import MongoClient
        _client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
        _client.admin.command("ping")   # fail fast if the URI/credentials are bad
        _collection = _client["quantumcanvas"]["runs"]
    except Exception as e:
        print(f"[mongo_logger] connection failed, mirror disabled: {e}")
        _collection = None
    return _collection


def mirror_file(circuit_hash: str, run_id: str, filename: str, content: Any) -> None:
    """
    Mirror one saved file into this circuit's Mongo document, under
    files.<sanitised-filename> (Mongo field names can't contain '.').
    """
    col = _get_collection()
    if col is None or not circuit_hash:
        return
    field = filename.replace(".", "_")
    try:
        col.update_one(
            {"circuit_hash": circuit_hash},
            {"$set": {"run_id": run_id, f"files.{field}": content}},
            upsert=True,
        )
    except Exception as e:
        print(f"[mongo_logger] write failed: {e}")
