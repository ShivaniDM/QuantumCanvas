from __future__ import annotations

import copy

MAX_SUGGESTIONS = 40


def _is(n, name, controls=0):
    return n["op"] == "gate" and n["params"].get("name") == name and len(n["controls"]) == controls


def _run(nodes, i, name):
    seen, j = [], i
    while j < len(nodes) and _is(nodes[j], name) and nodes[j]["targets"][0] not in seen:
        seen.append(nodes[j]["targets"][0])
        j += 1
    return seen, j - i


def _run_exact(nodes, i, name, want: set):
    got, length = _run(nodes, i, name)
    if set(got) == want and len(got) == len(want):
        return length
    if not want:
        return 0
    return None


def _mcz(nodes, i):
    if i < len(nodes) and nodes[i]["op"] == "gate" and nodes[i]["params"].get("name") == "z" and nodes[i]["controls"]:
        return sorted(nodes[i]["controls"] + nodes[i]["targets"]), 1
    if i + 2 < len(nodes) and _is(nodes[i], "h") and nodes[i + 1]["op"] == "gate" \
            and nodes[i + 1]["params"].get("name") == "x" and nodes[i + 1]["controls"] \
            and _is(nodes[i + 2], "h") and nodes[i]["targets"] == nodes[i + 1]["targets"] == nodes[i + 2]["targets"]:
        return sorted(nodes[i + 1]["controls"] + nodes[i + 1]["targets"]), 3
    return None, 0


def _match_amplify(nodes, i):
    h1, a = _run(nodes, i, "h")
    if len(h1) < 2:
        return None
    reg = set(h1)
    k = i + a
    b = _run_exact(nodes, k, "x", reg)
    if not b:
        return None
    k += b
    R, c = _mcz(nodes, k)
    if R is None or set(R) != reg:
        return None
    k += c
    d = _run_exact(nodes, k, "x", reg)
    if not d:
        return None
    k += d
    e = _run_exact(nodes, k, "h", reg)
    if not e:
        return None
    k += e
    return {"op": "boost", "targets": sorted(reg), "params": {}}, k - i


def _match_oracle(nodes, i, allow_bare):
    xs, a = _run(nodes, i, "x")
    R, c = _mcz(nodes, i + a)
    if R is None or len(R) < 2 or not set(xs) <= set(R):
        return None
    k = i + a + c
    b = _run_exact(nodes, k, "x", set(xs))
    if b is None:
        return None
    if not xs and not allow_bare(k):
        return None
    value = sum(1 << pos for pos, q in enumerate(R) if q not in xs)
    return {"op": "mark", "targets": list(R), "params": {"value": value}}, a + c + b


def _match_superpose(nodes, i):
    hs, a = _run(nodes, i, "h")
    if len(hs) < 2:
        return None
    return {"op": "shake", "targets": sorted(hs), "params": {}}, a


def _match_entangle(nodes, i):
    if i + 1 < len(nodes) and _is(nodes[i], "h") and _is(nodes[i + 1], "x", 1) \
            and nodes[i + 1]["controls"][0] == nodes[i]["targets"][0]:
        c, t = nodes[i + 1]["controls"][0], nodes[i + 1]["targets"][0]
        return [({"op": "shake", "targets": [c], "params": {}}, 1, i),
                ({"op": "entangle", "targets": [c, t], "params": {"style": "cx"}}, 1, i + 1)]
    return None


def _equivalent(gates, concept, n) -> bool:
    from qiskit.quantum_info import Operator
    from concepts import compile_document
    from concepts.emit_qiskit import build_circuit
    from mathlayer.layer import ref_circuit
    from qiskit import QuantumCircuit
    a = QuantumCircuit(n)
    for g in gates:
        a.compose(ref_circuit(g, n, {}), inplace=True)
    node = {"id": "lift", "op": concept["op"], "targets": concept["targets"], "controls": [], "ancillas": [],
            "classical": [], "params": concept["params"], "condition": None, "body": None, "ref": None,
            "repeat": 1, "metadata": {}}
    res = compile_document({"version": "0.4", "qubits": n, "classical_bits": 0, "operations": [node]})
    if not res.ok:
        return False
    return Operator(a).equiv(Operator(build_circuit(res.lowered)))


_TITLE = {"boost": "Amplitude amplification on {q}", "mark": "Oracle: mark |{bits}⟩ on {q}",
          "shake": "Superposition (H) on {q}", "entangle": "Entangle (CNOT) {c} → {t}"}


def _title(c):
    q = ", ".join(f"q{x}" for x in c["targets"])
    bits = format(c["params"].get("value", 0), f"0{len(c['targets'])}b") if c["op"] == "mark" else ""
    if c["op"] == "entangle":
        return _TITLE["entangle"].format(c=f"q{c['targets'][0]}", t=f"q{c['targets'][1]}")
    return _TITLE[c["op"]].format(q=q, bits=bits)


def suggest(nodes: list[dict], n: int) -> list[dict]:
    found = []
    i = 0
    while i < len(nodes) and len(found) < MAX_SUGGESTIONS:
        m = _match_amplify(nodes, i)
        if m:
            found.append((m[0], i, m[1])); i += m[1]; continue
        m = _match_oracle(nodes, i, lambda k: _match_amplify(nodes, k) is not None)
        if m:
            found.append((m[0], i, m[1])); i += m[1]; continue
        ent = _match_entangle(nodes, i)
        if ent:
            for concept, length, start in ent:
                found.append((concept, start, length))
            i += 2; continue
        m = _match_superpose(nodes, i)
        if m:
            found.append((m[0], i, m[1])); i += m[1]; continue
        i += 1
    out = []
    for concept, start, length in found:
        gates = nodes[start:start + length]
        ok = _equivalent(gates, concept, n)
        if not ok:
            continue
        lines = sorted({ln for g in gates for ln in g["metadata"].get("lines", [])})
        out.append({"id": f"s{len(out) + 1}", "title": _title(concept), "node_ids": [g["id"] for g in gates],
                    "lines": lines, "concept": copy.deepcopy(concept),
                    "check": {"level": "unitary", "ok": True,
                              "detail": f"the {length} gate{'s' if length != 1 else ''} and the concept are the same "
                                        "operation, up to global phase"}})
    return out
