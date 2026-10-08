"""Math layer (plan 9a). Seed tests ported from test_math_layer.py + golden log + coverage of every concept."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest
from qiskit import transpile
from qiskit_aer import AerSimulator

from conftest import make_doc, node as cnode
from concepts import compile_document
from concepts.angles import pi
from concepts.emit_qiskit import build_circuit
from mathlayer import analyze, analyze_document
from mathlayer.layer import Sim, ref_circuit, tvd
from problems import load_problems
from test_composites import teleport_doc

FIX = Path(__file__).parent / "fixtures" / "runs"
RUN = json.loads((FIX / "f9e60a7115d2.json").read_text(encoding="utf-8"))
GOLD = json.loads((FIX / "math_log_f9e60a7115d2.golden.json").read_text(encoding="utf-8"))


# ── seed helpers (same shapes as the seed test file) ─────────────────
def sn(i, op, t, params=None, classical=None):
    return {"id": i, "op": op, "targets": t, "params": params or {}, "classical": classical or []}


def srun(ops, n, nc, results):
    return {"run_id": "t", "ir_json": json.dumps({"version": "0.3", "qubits": n, "classical_bits": nc, "operations": ops}),
            "qiskit_py": "", "results": results}


def all_contracts(log):
    return [c for s in log["steps"] for c in s["contracts"]]


def check(log, name):
    return next(c for c in log["checks"] if c["check"].startswith(name))


def test_seed_bell_pair_all_contracts_hold():
    L = analyze(srun([sn("a", "shake", [0]), sn("b", "entangle", [0, 1]), sn("c", "measure", [0, 1], classical=[0, 1])],
                     2, 2, {"00": 507, "11": 493}))
    assert all(c["held"] for c in all_contracts(L)), all_contracts(L)
    assert L["predicted"] == {"00": 0.5, "11": 0.5}
    assert check(L, "observed")["ok"]


def test_seed_two_qubit_grover_boost_holds():
    L = analyze(srun([sn("a", "shake", [0, 1]), sn("b", "mark", [0, 1], {"value": 2}), sn("c", "boost", [0, 1]),
                      sn("d", "measure", [0, 1], classical=[0, 1])], 2, 2, {"10": 1000}))
    boost = [c for c in all_contracts(L) if "more likely" in c["claim"]][0]
    assert boost["held"], boost
    assert abs(L["predicted"]["10"] - 1) < 1e-9 and check(L, "observed")["ok"]


def test_seed_impossible_outcome_is_flagged():
    bad = srun([sn("a", "shake", [0]), sn("b", "entangle", [0, 1]), sn("c", "measure", [0, 1], classical=[0, 1])],
               2, 2, {"00": 500, "01": 500})
    assert check(analyze(bad), "observed")["ok"] is False


def test_seed_wrong_ratio_is_flagged():
    skew = srun([sn("a", "shake", [0]), sn("b", "entangle", [0, 1]), sn("c", "measure", [0, 1], classical=[0, 1])],
                2, 2, {"00": 800, "11": 200})
    assert check(analyze(skew), "observed")["ok"] is False


def test_seed_set_six_gives_110():
    s = srun([sn("a", "set", [0, 1, 2], {"value": 6}), sn("b", "measure", [0, 1, 2], classical=[0, 1, 2])], 3, 3, {"110": 100})
    assert analyze(s)["predicted"] == {"110": 1.0}


# ── golden log for run f9e60a7115d2 (M0.5 done-when) ─────────────────
def _subset(actual, golden, path=""):
    if isinstance(golden, dict):
        for k, v in golden.items():
            assert k in actual, f"missing {path}/{k}"
            _subset(actual[k], v, f"{path}/{k}")
    elif isinstance(golden, list):
        assert len(actual) == len(golden), f"{path}: {len(actual)} vs {len(golden)}"
        for i, (a, g) in enumerate(zip(actual, golden)):
            _subset(a, g, f"{path}[{i}]")
    else:
        assert actual == golden, f"{path}: {actual!r} != {golden!r}"


def test_golden_log_for_f9e60a7115d2_matches():
    _subset(analyze(RUN), GOLD)


def test_golden_facts_in_words():
    L = analyze(RUN)
    broken = sorted({s["id"] for s in L["steps"] for c in s["contracts"] if not c["held"]})
    assert broken == ["N3", "N6"]                                    # Shake (both qubits) and Boost contracts broken
    idle = sorted(s["id"] for s in L["steps"] if s.get("affects_result") is False)
    assert idle == ["N1", "N4", "N5", "N6"]
    p = float(check(L, "observed")["detail"].split("= ")[1])
    assert abs(p - 0.527) < 1e-3                                     # "p ≈ 0.53"
    assert L["ineffective_together"] is True


def test_the_code_of_the_reviewed_run_matches_its_ir_block_by_block():
    L = analyze(RUN)
    code = [c for c in L["checks"] if c["check"].startswith("code matches IR")]
    assert len(code) == 7 and all(c["ok"] for c in code)


# ── the code check really catches a wrong emitter ─────────────────────
def test_code_check_catches_a_tampered_gate():
    bad = copy.deepcopy(RUN)
    bad["qiskit_py"] = bad["qiskit_py"].replace("qc.cx(0, 1)", "qc.cx(1, 0)")
    L = analyze(bad)
    assert [c["ok"] for c in L["checks"] if "N4" in c["check"]] == [False]


def test_code_check_catches_a_dropped_block():
    bad = copy.deepcopy(RUN)
    bad["qiskit_py"] = "\n".join(l for l in bad["qiskit_py"].splitlines() if not l.startswith("# MARK"))
    assert any(c["ok"] is False and "align" in c["check"] for c in analyze(bad)["checks"])


def test_code_is_never_executed():
    bad = copy.deepcopy(RUN)
    bad["qiskit_py"] = bad["qiskit_py"].replace("qc.h(0)", "__import__('os').system('echo pwned > /tmp/pwned_math_layer')")
    L = analyze(bad)
    assert not Path("/tmp/pwned_math_layer").exists()
    assert any(c["ok"] is False for c in L["checks"])                  # refused, not run


# ── every concept: emitted code ≡ independent reference, prediction ≡ Aer ─
def sweep_docs():
    docs = {p["id"]: p["reference_solution"] for p in load_problems()}
    docs["controls"] = make_doc(4, [
        cnode(1, "shake", [0, 1, 2]), {"id": "c1", "op": "control", "controls": [0], "body": {"id": "b1", "op": "rotate", "targets": [1], "params": {"axis": "y", "angle": pi(1, 3)}}},
        {"id": "c2", "op": "control", "controls": [0, 1], "body": {"id": "b2", "op": "phase", "targets": [2], "params": {"angle": pi(1, 5)}}},
        {"id": "c3", "op": "control", "controls": [0], "body": {"id": "b3", "op": "swap", "targets": [1, 2]}},
        cnode(9, "measure", [0, 1, 2], classical=[0, 1, 2])], 3)
    docs["fourier_add"] = make_doc(3, [cnode(1, "shake", [0]), cnode(2, "fourier", [0, 1, 2]), cnode(3, "add", [0, 1, 2], params={"value": 3, "modulus": 8}),
                                       cnode(4, "fourier", [0, 1, 2], params={"inverse": True}), cnode(5, "measure", [0, 1, 2], classical=[0, 1, 2])], 3)
    docs["fourier_noswap"] = make_doc(3, [cnode(1, "set", [0, 1, 2], params={"value": 3}), cnode(2, "fourier", [0, 1, 2], params={"swaps": False}),
                                          cnode(3, "measure", [0, 1, 2], classical=[0, 1, 2])], 3)
    docs["eq_mark_via"] = make_doc(4, [cnode(1, "shake", [0, 1, 2]), cnode(2, "compare", [0, 1, 2], ancillas=[3], params={"value": 5}),
                                       cnode(3, "mark", [], params={"via": "op_2"}), cnode(4, "boost", [0, 1, 2]), cnode(5, "measure", [0, 1, 2], classical=[0, 1, 2])], 3)
    docs["neq_mark_via"] = make_doc(4, [cnode(1, "shake", [0, 1, 2]), cnode(2, "compare", [0, 1, 2], ancillas=[3], params={"operator": "neq", "value": 2}),
                                        cnode(3, "mark", [], params={"via": "op_2"}), cnode(4, "boost", [0, 1, 2]), cnode(5, "measure", [0, 1, 2], classical=[0, 1, 2])], 3)
    docs["zero_gate_steps"] = make_doc(2, [cnode(1, "set", [0, 1], params={"value": 0}), cnode(2, "phase", [0], params={"angle": pi(2)}),
                                           cnode(3, "flip", [1]), cnode(4, "measure", [0, 1], classical=[0, 1])], 2)
    docs["repeat_boost"] = make_doc(3, [cnode(1, "shake", [0, 1, 2]), cnode(2, "mark", [0, 1, 2], params={"value": 6}), cnode(3, "boost", [0, 1, 2], repeat=2),
                                        cnode(4, "measure", [0, 1, 2], classical=[0, 1, 2])], 3)
    docs["teleport_random"] = make_doc(3, teleport_doc(2.3), 3)
    docs["wrapped_compare"] = make_doc(5, [cnode(1, "shake", [0, 1, 2, 4]),
                                           {"id": "w", "op": "control", "controls": [4], "body": {"id": "wc", "op": "compare", "targets": [0, 1, 2], "ancillas": [3], "params": {"value": 5}}},
                                           cnode(9, "measure", [0, 1, 2, 3, 4], classical=[0, 1, 2, 3, 4])], 5)
    return docs


SWEEP = sweep_docs()


@pytest.mark.parametrize("name", list(SWEEP))
def test_every_concept_code_matches_the_independent_reference(name):
    res = compile_document(SWEEP[name])
    assert res.ok, [e.message for e in res.errors]
    L = analyze_document(SWEEP[name], qiskit_py=res.qiskit_py)
    code = [c for c in L["checks"] if c["check"].startswith("code")]
    assert code and all(c["ok"] for c in code), code


@pytest.mark.parametrize("name", list(SWEEP))
def test_predicted_distribution_matches_aer(name):
    doc = SWEEP[name]
    res = compile_document(doc)
    qc = build_circuit(res.lowered)
    if not any(i.operation.name == "measure" for i in qc.data):
        qc = qc.copy(); qc.measure_all()
    shots = 30000
    counts = AerSimulator().run(transpile(qc, AerSimulator()), shots=shots, seed_simulator=3).result().get_counts()
    counts = {k.replace(" ", ""): v for k, v in counts.items()}
    L = analyze_document(doc, qiskit_py=res.qiskit_py, results=counts)
    if "predicted" not in L or not L["predicted"]:
        pytest.skip("no measurement in this document")
    obs = {k: v / shots for k, v in counts.items()}
    assert tvd(obs, L["predicted"]) < 0.025, (L["predicted"], obs)
    assert check(L, "observed")["ok"], check(L, "observed")


def test_teleport_prediction_is_exact_for_the_sent_state():
    theta = 2.3
    L = analyze_document(make_doc(3, teleport_doc(theta), 3))
    p1_q2 = sum(v for k, v in L["predicted"].items() if k[0] == "1")
    assert abs(p1_q2 - np.sin(theta / 2) ** 2) < 1e-5            # log rounds to 6 decimals


def test_reuse_after_reset_is_predicted_zero():
    doc = make_doc(1, [cnode(1, "shake", [0]), cnode(2, "measure", [0], classical=[0]), cnode(3, "reset", [0]),
                       cnode(4, "measure", [0], classical=[1])], 2)
    L = analyze_document(doc)
    assert {k[0] for k in L["predicted"]} == {"0"}                    # clbit 1 (left char) is always 0 after Reset


# ── contracts per concept ────────────────────────────────────────────
def contracts_of(doc, step_id):
    L = analyze_document(doc)
    return next(s for s in L["steps"] if s["id"] == step_id)["contracts"]


def test_compare_contract_holds_with_fresh_ancilla_and_breaks_without():
    ok = make_doc(4, [cnode(1, "shake", [0, 1, 2]), cnode(2, "compare", [0, 1, 2], ancillas=[3], params={"value": 5})])
    assert contracts_of(ok, "op_2")[0]["held"]
    # a dirty flag qubit is a validator error, but the math layer must also notice it
    dirty = {"version": "0.3", "qubits": 4, "classical_bits": 0, "operations": [cnode(1, "flip", [3]), cnode(2, "shake", [0, 1, 2]),
             cnode(3, "compare", [0, 1, 2], ancillas=[3], params={"value": 5})]}
    c = contracts_of(dirty, "op_3")[0]
    assert c["held"] is False and "not fresh" in c["detail"]


def test_uncompute_contract_reports_helpers_back_at_zero():
    doc = make_doc(4, [cnode(1, "shake", [0, 1, 2]), cnode(2, "compare", [0, 1, 2], ancillas=[3], params={"value": 5}),
                       cnode(3, "phase", [3], params={"angle": pi(1)}), cnode(4, "uncompute", [], ref="op_2")])
    assert contracts_of(doc, "op_4")[0]["held"]


def test_add_contract_and_fourier_contract():
    doc = make_doc(3, [cnode(1, "shake", [0, 1]), cnode(2, "add", [0, 1, 2], params={"value": 3, "modulus": 8}),
                       cnode(3, "fourier", [0, 1, 2])])
    assert contracts_of(doc, "op_2")[0]["held"] and contracts_of(doc, "op_3")[0]["held"]


def test_boost_past_the_best_round_is_reported_with_the_trajectory():
    d = make_doc(2, [cnode(1, "shake", [0, 1]), cnode(2, "mark", [0, 1], params={"value": 3}), cnode(3, "boost", [0, 1], repeat=2)])
    c = contracts_of(d, "op_3")[0]
    assert c["held"] is False and "past the best round" in c["detail"] and "0.250 -> 1.000 -> 0.250" in c["detail"]


def test_boost_via_compare_uses_the_compared_value():
    d = make_doc(4, [cnode(1, "shake", [0, 1, 2]), cnode(2, "compare", [0, 1, 2], ancillas=[3], params={"value": 5}),
                     cnode(3, "mark", [], params={"via": "op_2"}), cnode(4, "boost", [0, 1, 2])])
    c = contracts_of(d, "op_4")[0]
    assert c["held"] and "marked answer 5" in c["claim"]


# ── reference semantics are independent of the compiler ──────────────
def test_reference_fourier_equals_qiskits_qftgate():
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import QFTGate
    from qiskit.quantum_info import Operator
    ir = json.loads(json.dumps(make_doc(3, [cnode(1, "fourier", [0, 1, 2])])))
    got = Operator(ref_circuit(ir["operations"][0], 3, {"op_1": ir["operations"][0]}))
    ref = QuantumCircuit(3); ref.append(QFTGate(3), range(3))
    assert got.equiv(Operator(ref))


def test_math_layer_does_not_import_the_compiler():
    src = (Path(__file__).parent.parent / "mathlayer" / "layer.py").read_text(encoding="utf-8")
    assert "from concepts" not in src and "import concepts" not in src


def test_too_large_circuits_are_skipped_not_faked():
    big = make_doc(21, [cnode(1, "shake", [0])])
    L = analyze_document(big)
    assert L["steps"] == [] and L["checks"][0]["ok"] is None and "too large" in L.get("skipped", "")


def test_unknown_future_op_is_skipped_with_a_reason():
    L = analyze_document({"version": "0.3", "qubits": 1, "classical_bits": 0, "operations": [{"id": "x", "op": "teleportation", "targets": [0]}]})
    assert any(c["ok"] is None for c in L["checks"])
