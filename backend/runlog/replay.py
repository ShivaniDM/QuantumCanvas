"""Replay: from a stored record alone, recompile and compare. Used by tests and by the audit endpoint."""
from __future__ import annotations

import json


def canvas_to_ir(canvas_json) -> dict | None:
    """Rebuild the Concept IR from the canvas snapshot saved with a run (concept steps + the legacy ops)."""
    from concepts.migrate import merge_canvas
    from concepts.schema import parse_document, to_dict
    c = canvas_json if isinstance(canvas_json, dict) else json.loads(canvas_json)
    snap = c.get("concepts")
    if not snap:
        return None
    nodes = [dict(n) for n in snap["nodes"]]
    return to_dict(parse_document(merge_canvas(snap.get("legacy_ir"), nodes, snap.get("classical_bits", 0))))


def replay(record: dict, rerun: bool = True) -> dict:
    """-> {"qiskit_identical", "distribution_identical", "roundtrip_identical", "counts_reproduced", details}
    counts_reproduced: for Aer runs, re-run with the SEED stored in the record and compare counts exactly."""
    from concepts import compile_document
    from mathlayer import analyze_document
    ir = record["input"]["ir_json"]
    ir = json.loads(ir) if isinstance(ir, str) else ir
    res = compile_document(ir)
    out = {"compiled_ok": res.ok, "roundtrip_identical": None}
    if not res.ok:
        out.update(qiskit_identical=False, distribution_identical=False, details="recompile failed: " + "; ".join(e.message for e in res.errors))
        return out
    out["qiskit_identical"] = res.qiskit_py == record["compile"]["qiskit_py"]
    stored = (record["results"].get("math_log") or {}).get("predicted")
    again = analyze_document(ir, qiskit_py=res.qiskit_py, code_check=False, counterfactual=False).get("predicted")
    out["distribution_identical"] = stored == again
    if record["input"].get("canvas_json"):
        try:
            rebuilt = canvas_to_ir(record["input"]["canvas_json"])
            out["roundtrip_identical"] = (rebuilt == ir) if rebuilt is not None else None
        except Exception as e:
            out["roundtrip_identical"] = False
            out["details"] = f"round-trip failed: {e}"
    ex = record["execution"]
    out["counts_reproduced"] = None
    if rerun and ex.get("backend_requested") == "aer" and ex.get("seed") is not None and record["results"].get("counts"):
        from aer_runner import run_aer_detailed
        from concepts.emit_qiskit import build_circuit
        again = run_aer_detailed(build_circuit(res.lowered), ex["shots"], seed=ex["seed"])
        out["counts_reproduced"] = again["counts"] == record["results"]["counts"]
    return out
