"""Golden test: every legacy canvas in fixtures/legacy compiles, after migration to Concept IR v0.3,
to an operator-equivalent circuit of what the old JS generator produced."""
import json
from pathlib import Path

import numpy as np
import pytest
from qiskit.quantum_info import Operator

from conftest import make_doc
from concepts import compile_document
from concepts.emit_qiskit import RUN_MARKER, build_circuit
from concepts.migrate import merge_canvas, migrate_legacy_ir, migrate_v02_to_v03

FIX = sorted((Path(__file__).parent / "fixtures" / "legacy").glob("*.json"))
assert FIX, "run `node make_legacy_fixtures.js` in backend/tests to create the fixtures"


def legacy_circuit(code):
    ns = {}
    exec(compile(code.split(RUN_MARKER)[0], "<legacy>", "exec"), ns)
    return ns["qc"]


def unitary(qc):
    return Operator(qc.remove_final_measurements(inplace=False))


def measures(qc):
    return sorted((qc.find_bit(i.qubits[0]).index, qc.find_bit(i.clbits[0]).index)
                  for i in qc.data if i.operation.name == "measure")


@pytest.mark.parametrize("path", FIX, ids=lambda p: p.stem)
def test_migrated_circuit_matches_legacy_generator(path):
    fx = json.loads(path.read_text(encoding="utf-8"))
    doc = migrate_legacy_ir(fx["ir"])
    res = compile_document(doc)
    assert res.ok, [e.message for e in res.errors]
    new, old = build_circuit(res.lowered), legacy_circuit(fx["qiskit"])
    if fx["name"] == "double_boost":
        pytest.skip("covered by test_consecutive_boost_clicks_each_apply_a_diffuser")
    assert np.allclose(unitary(new).data, unitary(old).data) or unitary(new).equiv(unitary(old))
    assert measures(new) == measures(old)


def test_consecutive_boost_clicks_each_apply_a_diffuser():
    """Deliberate difference: the legacy generator merged back-to-back Boost clicks into ONE
    diffuser although its pseudocode said 'N x'. v0.3 applies one diffuser per click."""
    fx = json.loads((Path(__file__).parent / "fixtures" / "legacy" / "double_boost.json").read_text(encoding="utf-8"))
    doc = migrate_legacy_ir(fx["ir"])
    assert [o["op"] for o in doc["operations"]].count("boost") == 2
    boosts = [o for o in doc["operations"] if o["op"] == "boost"]
    new = unitary(build_circuit(compile_document(doc).lowered))
    old = unitary(legacy_circuit(fx["qiskit"]))
    assert not np.allclose(new.data, old.data)
    single = dict(doc, operations=[o for o in doc["operations"] if o is not boosts[1]])
    assert np.allclose(unitary(build_circuit(compile_document(single).lowered)).data, old.data)


def test_alias_name_from_the_plan():
    assert migrate_v02_to_v03 is migrate_legacy_ir


def test_merge_orders_new_nodes_by_click_sequence():
    fx = json.loads((Path(__file__).parent / "fixtures" / "legacy" / "grover_2q_mark_q2.json").read_text(encoding="utf-8"))
    ir = fx["ir"]
    # the legacy clicks used seq 0..5; slip a new Flip between Shake(q2)=seq1 and Mark=seq2
    flip = {"id": "N1", "op": "flip", "targets": [0], "seq": 1.5}
    doc = merge_canvas(ir, [flip])
    ops = [o["op"] for o in doc["operations"]]
    assert ops == ["shake", "flip", "mark", "boost", "measure"]
    assert all("seq" not in o for o in doc["operations"])
    assert compile_document(doc).ok


def test_new_node_between_marks_splits_the_oracle():
    fx = json.loads((Path(__file__).parent / "fixtures" / "legacy" / "grover_3q_mark_q1_q3.json").read_text(encoding="utf-8"))
    marks = [o for o in migrate_legacy_ir(fx["ir"])["operations"] if o["op"] == "mark"]
    assert len(marks) == 1 and marks[0]["params"]["value"] == 5        # q1 and q3 marked together
    split = merge_canvas(fx["ir"], [{"id": "N", "op": "flip", "targets": [1], "seq": 3.5}])
    assert [o["op"] for o in split["operations"]].count("mark") == 2


def test_legacy_measure_uses_classical_bit_equal_to_qubit_index():
    fx = json.loads((Path(__file__).parent / "fixtures" / "legacy" / "bell_pair.json").read_text(encoding="utf-8"))
    doc = migrate_legacy_ir(fx["ir"])
    m = [o for o in doc["operations"] if o["op"] == "measure"][0]
    assert m["classical"] == m["targets"] and doc["classical_bits"] == 2


def test_empty_legacy_ir_gives_empty_document():
    assert migrate_legacy_ir({"qubits": [], "edges": []})["operations"] == []
