from typing import Any
from config import settings

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    if not settings.MONGODB_URI:
        return None
    try:
        import certifi
        from pymongo import MongoClient
        _client = MongoClient(
            settings.MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            tlsCAFile=certifi.where(),
        )
        _client.admin.command("ping")
        _collection = _client["quantumcanvas"]["runs"]
    except Exception as e:
        print(f"[mongo_logger] connection failed, mirror disabled: {e}")
        _collection = None
    return _collection


def mirror_file(circuit_hash: str, run_id: str, filename: str, content: Any) -> None:
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
