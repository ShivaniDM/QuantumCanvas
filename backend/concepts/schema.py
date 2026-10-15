from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "0.4"

PRIMITIVES = ("shake", "set", "flip", "phase", "rotate", "swap", "measure", "reset", "gate")
MODIFIERS = ("control", "correct")
COMPOSITES = ("entangle", "encode", "compare", "mark", "boost", "fourier", "add", "uncompute")
ALL_OPS = PRIMITIVES + MODIFIERS + COMPOSITES

NON_UNITARY_OPS = ("measure", "reset", "correct")


@dataclass
class Node:
    id: str
    op: str
    targets: list[int] = field(default_factory=list)
    controls: list[int] = field(default_factory=list)
    ancillas: list[int] = field(default_factory=list)
    classical: list[int] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    condition: dict | None = None
    body: "Node | None" = None
    ref: str | None = None
    repeat: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    version: str = SCHEMA_VERSION
    qubits: int = 0
    classical_bits: int = 0
    operations: list[Node] = field(default_factory=list)


class SchemaError(ValueError):
    pass


def _ints(v, field_name, node_id):
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
        raise SchemaError(f"{node_id}: '{field_name}' must be a list of integers")
    return list(v)


def parse_node(d: dict, path: str = "operations") -> Node:
    if not isinstance(d, dict):
        raise SchemaError(f"{path}: a node must be an object")
    nid = d.get("id")
    if not isinstance(nid, str) or not nid:
        raise SchemaError(f"{path}: every node needs a string 'id'")
    op = d.get("op")
    if not isinstance(op, str):
        raise SchemaError(f"{nid}: every node needs a string 'op'")
    body = d.get("body")
    repeat = d.get("repeat", 1)
    if isinstance(repeat, bool) or not isinstance(repeat, int):
        raise SchemaError(f"{nid}: 'repeat' must be an integer")
    params = d.get("params") or {}
    if not isinstance(params, dict):
        raise SchemaError(f"{nid}: 'params' must be an object")
    cond = d.get("condition")
    if cond is not None and not isinstance(cond, dict):
        raise SchemaError(f"{nid}: 'condition' must be an object or null")
    return Node(
        id=nid, op=op,
        targets=_ints(d.get("targets"), "targets", nid),
        controls=_ints(d.get("controls"), "controls", nid),
        ancillas=_ints(d.get("ancillas"), "ancillas", nid),
        classical=_ints(d.get("classical"), "classical", nid),
        params=params, condition=cond,
        body=parse_node(body, f"{nid}.body") if body else None,
        ref=d.get("ref"), repeat=repeat,
        metadata=d.get("metadata") or {},
    )


def parse_document(d: dict) -> Document:
    if not isinstance(d, dict):
        raise SchemaError("document must be an object")
    q = d.get("qubits", 0)
    c = d.get("classical_bits", 0)
    for name, v in (("qubits", q), ("classical_bits", c)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise SchemaError(f"'{name}' must be a non-negative integer")
    ops = d.get("operations", [])
    if not isinstance(ops, list):
        raise SchemaError("'operations' must be a list")
    return Document(
        version=str(d.get("version", SCHEMA_VERSION)), qubits=q, classical_bits=c,
        operations=[parse_node(o, f"operations[{i}]") for i, o in enumerate(ops)],
    )


def node_to_dict(n: Node) -> dict:
    return {
        "id": n.id, "op": n.op, "targets": list(n.targets), "controls": list(n.controls),
        "ancillas": list(n.ancillas), "classical": list(n.classical),
        "params": n.params, "condition": n.condition,
        "body": node_to_dict(n.body) if n.body else None,
        "ref": n.ref, "repeat": n.repeat, "metadata": n.metadata,
    }


def to_dict(doc: Document) -> dict:
    return {
        "version": doc.version, "qubits": doc.qubits, "classical_bits": doc.classical_bits,
        "operations": [node_to_dict(n) for n in doc.operations],
    }


def walk(nodes):
    for n in nodes:
        yield n
        if n.body is not None:
            yield from walk([n.body])
