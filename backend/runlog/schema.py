"""JSON Schema for run record v2 (plan 9c). A record that does not validate is never silently dropped:
the save raises RecordInvalid and the caller surfaces it to the user."""

_str = {"type": "string"}
_strnull = {"type": ["string", "null"]}
_obj = {"type": "object"}

RUN_RECORD_V2 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "quantumcanvas.run/v2",
    "type": "object",
    "required": ["schema", "run_id", "revision", "status", "identity", "versions", "input", "compile", "execution",
                 "results", "explanation", "errors", "flags", "edit_history"],
    "properties": {
        "schema": {"const": "quantumcanvas.run/v2"},
        "run_id": {"type": "string", "minLength": 6},
        "revision": {"type": "integer", "minimum": 1},
        "status": {"enum": ["ok", "error", "submitted", "running"]},
        "identity": {
            "type": "object",
            "required": ["session_id", "user", "created_at", "circuit_hash", "circuit_folder"],
            "properties": {"session_id": _strnull, "user": _str, "created_at": _str, "finished_at": _strnull,
                           "parent_run_id": _strnull, "circuit_hash": _strnull, "circuit_folder": _strnull}},
        "versions": {"type": "object", "required": ["app_git_sha", "compiler", "ir_schema", "math_layer", "qiskit"],
                     "properties": {"app_git_sha": _str, "compiler": _str, "ir_schema": _str,
                                    "math_layer": _strnull, "qiskit": _strnull, "qiskit_aer": _strnull}},
        "input": {"type": "object", "required": ["canvas_json", "ir_json", "validator_errors", "validator_warnings"],
                  "properties": {"canvas_json": {"type": ["object", "string", "null"]}, "ir_json": {"type": ["object", "string", "null"]},
                                 "validator_errors": {"type": "array"}, "validator_warnings": {"type": "array"}}},
        "compile": {"type": "object", "required": ["ir_hash", "gates", "trace", "qiskit_py", "qasm3", "pseudocode"],
                    "properties": {"ir_hash": _strnull, "gates": {"type": ["array", "null"]}, "trace": {"type": ["array", "null"]},
                                   "qiskit_py": _strnull, "qiskit_py_displayed": _strnull, "qasm3": _strnull,
                                   "pseudocode": {"type": ["object", "string", "null"]}}},
        "execution": {"type": "object",
                      "required": ["backend_requested", "backend_executed", "shots", "seed"],
                      "properties": {"backend_requested": _str, "backend_executed": _strnull, "provider_job_id": _strnull,
                                     "provider_status": _strnull, "shots": {"type": ["integer", "null"]}, "seed": {"type": ["integer", "null"]},
                                     "transpiled": {"type": ["object", "null"]}, "timing": {"type": "object"},
                                     "cost": {"type": ["object", "null"]}, "raw_provider_response": {}}},
        "results": {"type": "object", "required": ["counts", "math_log", "result_check"],
                    "properties": {"counts": {"type": ["object", "null"]}, "math_log": {"type": ["object", "null"]},
                                   "result_check": {"type": ["object", "null"]}}},
        "explanation": {"type": "object", "required": ["template", "llm"],
                        "properties": {"template": {"type": ["array", "null"]}, "llm": {"type": ["object", "null"]}}},
        "errors": {"type": "array", "items": {"type": "object", "required": ["stage", "code", "message"],
                                              "properties": {"stage": {"enum": ["validate", "compile", "submit", "fetch", "math", "explain", "save"]},
                                                             "code": _str, "message": _str}}},
        "flags": {"type": "array", "items": {"type": "object", "required": ["flag", "detail"],
                                             "properties": {"flag": _str, "detail": _str}}},
        "edit_history": {"type": "array"},
    },
}
