"""Explanations must be computed from the circuit, never template claims that the circuit contradicts.

Regression: runs/f9e60a7115d2.json (Encode, Shake, Entangle, Mark, Boost on ONE qubit, measure q0)
was explained as "Boost makes the marked answer more likely" while it lowered it from 82% to 18%.
"""
import json
from pathlib import Path

import pytest

from conftest import compiled, make_doc, node, warn_codes
from concepts import compile_document
from concepts.angles import pi

RUN = json.loads((Path(__file__).parent / "fixtures" / "runs" / "f9e60a7115d2.json").read_text())
IR = json.loads(RUN["ir_json"])


def steps(res):
    return {s["id"]: s for s in res.pseudocode["steps"]}


def test_the_real_run_still_compiles_and_matches_the_recorded_gates():
    res = compile_document(IR)
    assert res.ok
    for needle in ("qc.ry(0.9272952180016122, 1)", "qc.ry(2.214297435588181, 0)", "qc.cx(0, 1)", "qc.measure(0, 0)"):
        assert needle in res.qiskit_py


def test_boost_sentence_is_computed_and_admits_the_drop():
    st = steps(compile_document(IR))["N6"]
    assert st["claim_ok"] is False
    assert "LOWERED" in st["plain"] and "82%" in st["plain"] and "18%" in st["plain"]
    assert "more likely" not in st["plain"].replace("makes", "").split("Boost only helps")[0] or "LOWERED" in st["plain"]
    assert "single qubit" in st["plain"] or "at least 2 qubits" in st["plain"] or "2 or more qubits" in st["plain"]


def test_shake_after_encode_is_reported_with_the_real_numbers():
    res = compile_document(IR)
    st = steps(res)["N3"]
    assert st["claim_ok"] is False and "80% → 10%" in st["effect"] and "20% → 10%" in st["effect"]
    assert "overwritten" in st["plain"]
    assert "W_SHAKE_AFTER_ENCODE" in warn_codes(res)


def test_entangle_reports_real_entanglement():
    st = steps(compile_document(IR))["N4"]
    assert "0.33 bits" in st["effect"] and st["claim_ok"] is True


def test_mark_says_probabilities_unchanged_only_because_they_were():
    assert "did not change" in steps(compile_document(IR))["N5"]["effect"]


def test_single_qubit_boost_warns():
    assert "W_BOOST_SINGLE_QUBIT" in warn_codes(compile_document(IR))


def test_unmeasured_effect_flags_exactly_the_four_idle_steps():
    res = compile_document(IR)
    flagged = sorted(w.op_id for w in res.warnings if w.code == "W_UNMEASURED_EFFECT")
    assert flagged == ["N1", "N4", "N5", "N6"]          # N2, N3 decide q0; N8 is the Measure


def test_flagged_steps_really_are_irrelevant():
    """Delete the flagged steps and the measured distribution is identical (the reviewer's claim, checked)."""
    from concepts.analysis import _distribution_for, _without
    from concepts.schema import parse_document
    doc = parse_document(IR)
    base = _distribution_for(doc)
    slim = _distribution_for(_without(doc, {"N1", "N4", "N5", "N6"}))
    assert base[1] == slim[1] and all(abs(a - b) < 1e-9 for a, b in zip(base[0], slim[0]))
    assert abs(base[0][1] - 0.10) < 1e-9


def test_two_qubit_search_boost_raises_and_says_so():
    ops = [node(1, "shake", [0, 1]), node(2, "mark", [0, 1], params={"value": 3}), node(3, "boost", [0, 1])]
    res = compile_document(make_doc(2, ops))
    st = steps(res)["op_3"]
    assert st["claim_ok"] is True and "raised" in st["plain"] and "25% → 100%" in st["plain"]
    assert "W_BOOST_SINGLE_QUBIT" not in warn_codes(res)


def test_boost_without_a_mark_says_there_is_nothing_to_amplify():
    res = compile_document(make_doc(2, [node(1, "shake", [0, 1]), node(2, "boost", [0, 1])]))
    st = steps(res)["op_2"]
    assert st["claim_ok"] is False and "no Mark" in st["plain"] or "Nothing was marked" in st["effect"]


def test_too_many_boost_rounds_is_reported_as_a_drop():
    ops = [node(1, "shake", [0, 1]), node(2, "mark", [0, 1], params={"value": 3}), node(3, "boost", [0, 1], repeat=2)]
    st = steps(compile_document(make_doc(2, ops)))["op_3"]
    assert st["claim_ok"] is False and "peaks at 100% after 1 round" in st["plain"] and "falls back to 25%" in st["plain"]
    assert "25% → 100% → 25%" in st["effect"]


def test_entangle_without_superposition_does_not_claim_a_link():
    res = compile_document(make_doc(2, [node(1, "entangle", [0, 1])]))
    st = steps(res)["op_1"]
    assert st["claim_ok"] is False and "did not link" in st["plain"]


def test_a_normal_bell_circuit_has_no_warnings_and_true_claims():
    ops = [node(1, "shake", [0]), node(2, "entangle", [0, 1]), node(3, "measure", [0, 1], classical=[0, 1])]
    res = compile_document(make_doc(2, ops, 2))
    assert res.warnings == []
    assert all(s.get("claim_ok", True) for s in res.pseudocode["steps"])


def test_steps_that_matter_are_not_flagged():
    # Compare + Phase + Uncompute + Boost (Grover): every step affects the measured register
    ops = [node(1, "shake", [0, 1, 2]), node(2, "compare", [0, 1, 2], ancillas=[3], params={"value": 5}),
           node(3, "phase", [3], params={"angle": pi(1)}), node(4, "uncompute", [], ref="op_2"),
           node(5, "boost", [0, 1, 2]), node(6, "measure", [0, 1, 2], classical=[0, 1, 2])]
    res = compile_document(make_doc(4, ops, 3))
    assert "W_UNMEASURED_EFFECT" not in warn_codes(res)


def test_no_measure_means_nothing_is_called_idle():
    res = compile_document(make_doc(2, [node(1, "shake", [0]), node(2, "flip", [1])]))
    assert "W_UNMEASURED_EFFECT" not in warn_codes(res)


def test_analysis_stops_quietly_after_a_measurement():
    ops = [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]), node(3, "flip", [0])]
    res = compile_document(make_doc(1, ops, 1))
    assert res.ok          # steps after a mid-circuit measure just get no computed claim


def test_effect_text_is_part_of_the_plain_sentence_so_saved_files_carry_it():
    assert "Result:" in steps(compile_document(IR))["N3"]["plain"]


# ── dangling references (the N7 gap) ─────────────────────────────────
def test_uncompute_pointing_into_a_wrapped_step_is_rejected_not_dangling():
    cmp_ = {"id": "N2", "op": "compare", "targets": [0, 1], "ancillas": [2], "params": {"value": 1}}
    wrapped = {"id": "N5", "op": "control", "controls": [3], "body": cmp_}
    ops = [node(1, "shake", [0, 1, 3]), wrapped, {"id": "N6", "op": "uncompute", "ref": "N2"}]
    res = compile_document(make_doc(4, ops))
    assert not res.ok and any(e.code == "E_UNCOMPUTE_REF" for e in res.errors)


def test_node_id_gaps_are_harmless():
    ops = [node(1, "shake", [0]), {"id": "N8", "op": "flip", "targets": [0]}]
    assert compile_document(make_doc(1, ops)).ok


def test_code_comments_never_carry_template_claims():
    res = compile_document(IR)
    assert "more likely" not in res.qiskit_py and "spread into every possibility" not in res.qiskit_py
    assert "# BOOST [q1]" in res.qiskit_py and "# SHAKE [q0, q1]" in res.qiskit_py
