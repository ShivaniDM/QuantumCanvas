"""Legacy canvas IR (the 5-concept per-qubit IR from frontend/js/ir.js) -> Concept IR v0.3.

Also merges the canvas' new concept nodes (which carry a click-order ``seq``) with the
legacy ops by that same ``seq``, so Shake -> Compare -> Mark -> ... keeps the order the
learner actually clicked.

Mapping (verified against frontend/js/qiskit-generator.js):
  Shake  -> shake            Link  -> entangle (style cx, control = source)
  Look   -> measure          Boost -> boost on ALL qubits (one node per click)
  Mark   -> mark on ALL qubits, value = sum of 2**i over the marked qubits in that
            batch (the legacy oracle flips X on unmarked qubits then MCZs everything)

Known difference, on purpose: the legacy pipeline merged consecutive Boost clicks into
ONE diffuser even though its pseudocode said "N x". v0.3 applies one diffuser per click.
"""
from __future__ import annotations

from .schema import SCHEMA_VERSION

_LEGACY_OPS = ("shake", "mark", "boost", "link", "look")


def _entries(ir: dict) -> list[dict]:
    """Flatten the per-qubit tagged ops into one chronological list (same sort as ir.js)."""
    idx_of = {q["id"]: i for i, q in enumerate(ir.get("qubits", []))}
    out = []
    for q in ir.get("qubits", []):
        tagged = q.get("taggedOps")
        if tagged is None:       # very old logs: plain op names only
            tagged = [{"op": o, "seq": None} for o in q.get("ops", [])]
        for i, t in enumerate(tagged):
            if isinstance(t, str):
                t = {"op": t, "seq": None}
            if t.get("op") not in _LEGACY_OPS:
                continue
            seq = t.get("seq")
            out.append({"qid": q["id"], "idx": idx_of[q["id"]], "op": t["op"],
                        "seq": seq if seq is not None else i * 0.001,
                        "correlated": bool(t.get("correlated", False))})
    out.sort(key=lambda e: (e["seq"], 1 if e["correlated"] else 0))
    return out


def _legacy_nodes(ir: dict, new_seqs: list[float]) -> list[tuple[float, dict]]:
    """Group consecutive legacy entries like the old pseudocode did, but never across a new node."""
    n = len(ir.get("qubits", []))
    edges = ir.get("edges", [])
    entries = _entries(ir)
    idx_of = {q["id"]: i for i, q in enumerate(ir.get("qubits", []))}

    def new_between(a, b):
        return any(a < s < b for s in new_seqs)

    nodes: list[tuple[float, dict]] = []
    k = 0
    i = 0
    while i < len(entries):
        op = entries[i]["op"]
        batch = [entries[i]]
        i += 1
        while i < len(entries) and entries[i]["op"] == op and not new_between(batch[-1]["seq"], entries[i]["seq"]):
            if op == "boost" and entries[i]["seq"] != batch[-1]["seq"]:
                break                      # one Boost node per click
            batch.append(entries[i])
            i += 1
        seq0 = batch[0]["seq"]
        k += 1
        nid = f"L{k}"
        meta = {"legacy": True, "tool": op}
        if op == "shake":
            tg = list(dict.fromkeys(e["idx"] for e in batch))
            nodes.append((seq0, {"id": nid, "op": "shake", "targets": tg, "metadata": meta}))
        elif op == "mark":
            marked = {e["idx"] for e in batch}
            nodes.append((seq0, {"id": nid, "op": "mark", "targets": list(range(n)),
                                 "params": {"value": sum(1 << m for m in marked)}, "metadata": meta}))
        elif op == "boost":
            nodes.append((seq0, {"id": nid, "op": "boost", "targets": list(range(n)), "metadata": meta}))
        elif op == "link":
            done = set()
            by_seq: dict[float, list[int]] = {}
            for e in batch:
                by_seq.setdefault(e["seq"], []).append(e["idx"])
            for s, qs in by_seq.items():
                for ei, ed in enumerate(edges):
                    pair = {idx_of.get(ed["src"]), idx_of.get(ed["tgt"])}
                    if pair <= set(qs) and ei not in done:
                        done.add(ei)
                        nodes.append((s, {"id": f"{nid}.{ei}", "op": "entangle",
                                          "targets": [idx_of[ed["src"]], idx_of[ed["tgt"]]],
                                          "params": {"style": "cx"}, "metadata": meta}))
                        break
        elif op == "look":
            direct = [e["idx"] for e in batch if not e["correlated"]]
            corr = [e["idx"] for e in batch if e["correlated"]]
            tg = list(dict.fromkeys(direct + corr))
            nodes.append((seq0, {"id": nid, "op": "measure", "targets": tg, "classical": list(tg),
                                 "metadata": meta}))
    return nodes


def migrate_legacy_ir(ir: dict) -> dict:
    """Legacy IR -> Concept IR v0.3 (no new nodes)."""
    return merge_canvas(ir, [])


migrate_v02_to_v03 = migrate_legacy_ir   # name used in the design plan


def merge_canvas(legacy_ir: dict | None, new_nodes: list[dict], classical_bits: int = 0) -> dict:
    """Legacy IR + new concept nodes (each with a numeric ``seq``) -> one Concept IR document."""
    legacy_ir = legacy_ir or {"qubits": [], "edges": []}
    n = len(legacy_ir.get("qubits", []))
    new_seqs = [float(nn.get("seq", 0)) for nn in new_nodes]
    timeline = _legacy_nodes(legacy_ir, new_seqs)
    for nn in new_nodes:
        d = {k: v for k, v in nn.items() if k != "seq"}
        timeline.append((float(nn.get("seq", 0)), d))
    # stable: equal seq keeps legacy first
    timeline.sort(key=lambda t: t[0])
    ops = [d for _, d in timeline]

    cb = classical_bits
    if any(d["op"] == "measure" and d.get("metadata", {}).get("legacy") for d in ops):
        cb = max(cb, n)
    for d in ops:
        for c in d.get("classical", []) or []:
            cb = max(cb, c + 1)
        b = d.get("body") or {}
        for c in b.get("classical", []) or []:
            cb = max(cb, c + 1)
    return {"version": SCHEMA_VERSION, "qubits": n, "classical_bits": cb, "operations": ops}
