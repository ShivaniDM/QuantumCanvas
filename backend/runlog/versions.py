from __future__ import annotations

import os
import subprocess
from importlib import metadata

COMPILER_VERSION = "0.3.1"
IR_SCHEMA_VERSION = "0.3"
RECORD_SCHEMA = "quantumcanvas.run/v2"


def _pkg(name):
    try:
        return metadata.version(name)
    except Exception:
        return None


def app_git_sha() -> str:
    for env in ("GIT_SHA", "GITHUB_SHA", "SOURCE_VERSION", "WEBSITE_COMMIT_ID", "COMMIT_SHA"):
        if os.environ.get(env):
            return os.environ[env]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, timeout=3).decode().strip()
    except Exception:
        return "unknown"


def collect() -> dict:
    try:
        from mathlayer import VERSION as ML
    except Exception:
        ML = None
    return {"app_git_sha": app_git_sha(), "compiler": COMPILER_VERSION, "ir_schema": IR_SCHEMA_VERSION, "record_schema": RECORD_SCHEMA,
            "math_layer": ML, "qiskit": _pkg("qiskit"), "qiskit_aer": _pkg("qiskit-aer"), "requests": _pkg("requests"),
            "numpy": _pkg("numpy")}
