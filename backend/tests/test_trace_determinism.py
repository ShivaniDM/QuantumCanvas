from conftest import compiled, node
from concepts import compile_document
from concepts.angles import pi

DOC_OPS = [node(1, "shake", [0, 1, 2]),
           node(2, "compare", [0, 1, 2], ancillas=[3], params={"value": 5}),
           node(3, "mark", [], params={"via": "op_2"}),
           node(4, "boost", [0, 1, 2], repeat=2),
           node(5, "fourier", [0, 1, 2]),
           node(6, "entangle", [0, 1]),
           node(7, "measure", [0, 1, 2], classical=[0, 1, 2])]


def test_every_gate_has_a_trace_entry():
    r = compiled(4, DOC_OPS, 3)
    assert len(r.trace) == len(r.gates) > 0
    assert all(len(chain) >= 1 for chain in r.trace)


def test_union_of_a_nodes_gates_is_exactly_what_the_how_view_highlights():
    r = compiled(4, DOC_OPS, 3)
    for op_id, idxs in r.node_ranges.items():
        from_trace = [i for i, chain in enumerate(r.trace) if chain[-1] == op_id]
        assert from_trace == idxs
    # ranges partition the gate list in order
    flat = [i for ids in r.node_ranges.values() for i in ids]
    assert flat == list(range(len(r.gates)))


def test_composite_children_carry_their_parent_chain():
    r = compiled(4, DOC_OPS, 3)
    mark_chains = [c for c in r.trace if c[-1] == "op_3"]
    assert mark_chains and all(len(c) >= 2 for c in mark_chains)          # child id first, parent last
    assert any(c[0] == "op_3.u" or "op_2" in c for c in mark_chains)        # the Uncompute reuses Compare's gates


def test_line_to_gate_map_covers_all_gates():
    r = compiled(4, DOC_OPS, 3)
    covered = sorted(i for gs in r.line_gates for i in gs)
    assert covered == list(range(len(r.gates)))
    assert len(r.qiskit_lines) == len(r.line_gates)


def test_compiling_twice_is_byte_identical():
    a = compile_document({"version": "0.3", "qubits": 4, "classical_bits": 3, "operations": DOC_OPS}, backend="ionq", with_qasm=True)
    b = compile_document({"version": "0.3", "qubits": 4, "classical_bits": 3, "operations": DOC_OPS}, backend="ionq", with_qasm=True)
    import json
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)
    assert a.qiskit_py == b.qiskit_py and a.qasm3 == b.qasm3


def test_references_read_as_step_numbers_not_internal_ids():
    r = compiled(4, DOC_OPS, 3)
    mark = next(s for s in r.pseudocode["steps"] if s["id"] == "op_3")
    assert "step 2" in mark["code"] and "op_2" not in mark["code"]
    unc = compiled(2, [node(1, "compare", [0], ancillas=[1], params={"value": 1}), node(2, "uncompute", [], ref="op_1")])
    assert "UNCOMPUTE step 1" in [s for s in unc.pseudocode["steps"] if s["id"] == "op_2"][0]["code"]
