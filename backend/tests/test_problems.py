"""Every problem's reference solution must pass its own check; obviously wrong answers must not."""
import copy

import pytest

from problems import check_solution, get_problem, load_problems, public_view

PROBS = load_problems()


def test_there_are_fourteen_seed_problems():
    assert len(PROBS) == 14 and len({p["id"] for p in PROBS}) == 14


@pytest.mark.parametrize("p", PROBS, ids=lambda p: p["id"])
def test_reference_solution_passes_its_own_check(p):
    r = check_solution(p, p["reference_solution"])
    assert r["passed"], r


def test_public_view_hides_the_answer():
    v = public_view(PROBS[0])
    assert "reference_solution" not in v and "check" not in v and v["statement"]


def empty(p):
    d = copy.deepcopy(p["reference_solution"])
    d["operations"] = []
    return d


@pytest.mark.parametrize("p", PROBS, ids=lambda p: p["id"])
def test_empty_circuit_never_passes(p):
    assert not check_solution(p, empty(p))["passed"]


def test_wrong_rotation_fails_bias_problem():
    p = get_problem("p_bias_075")
    bad = copy.deepcopy(p["reference_solution"]); bad["operations"][0]["params"]["angle"] = {"pi": [1, 3]}
    r = check_solution(p, bad)
    assert not r["passed"] and "|1⟩" in r["summary"]


def test_disallowed_concept_is_rejected():
    p = get_problem("p_set_five")
    bad = {"version": "0.3", "qubits": 3, "classical_bits": 0, "operations": [
        {"id": "a", "op": "shake", "targets": [0]}]}
    r = check_solution(p, bad)
    assert not r["passed"] and "allows" in r["summary"]


def test_wrong_qubit_count_is_rejected():
    p = get_problem("p_set_five")
    bad = copy.deepcopy(p["reference_solution"]); bad["qubits"] = 4
    assert "exactly 3 qubits" in check_solution(p, bad)["summary"]


def test_validator_errors_surface_in_plain_language():
    p = get_problem("p_set_five")
    bad = copy.deepcopy(p["reference_solution"]); bad["operations"][0]["params"]["value"] = 9
    r = check_solution(p, bad)
    assert not r["passed"] and r["errors"] and "needs" in r["summary"]


def test_opposite_vs_same_are_distinguished():
    same, opp = get_problem("p_same"), get_problem("p_opposite")
    assert not check_solution(opp, same["reference_solution"])["passed"]
    assert not check_solution(same, opp["reference_solution"])["passed"]


def test_teleport_without_corrections_fails():
    p = get_problem("p_teleport")
    bad = copy.deepcopy(p["reference_solution"])
    bad["operations"] = [o for o in bad["operations"] if o["op"] != "correct"]
    assert not check_solution(p, bad)["passed"]


def test_teleport_missing_the_phase_fix_fails():
    p = get_problem("p_teleport")
    bad = copy.deepcopy(p["reference_solution"])
    bad["operations"] = [o for o in bad["operations"] if o["id"] != "r8"]
    assert not check_solution(p, bad)["passed"]


def test_fourier_needs_both_directions():
    p = get_problem("p_fourier_roundtrip")
    bad = copy.deepcopy(p["reference_solution"]); bad["operations"] = bad["operations"][:1]
    assert not check_solution(p, bad)["passed"]


def test_add_wrong_constant_fails():
    p = get_problem("p_add_three")
    bad = copy.deepcopy(p["reference_solution"]); bad["operations"][0]["params"]["value"] = 4
    assert not check_solution(p, bad)["passed"]


def test_one_grover_round_is_not_enough_for_five():
    p = get_problem("p_find_five")
    d = copy.deepcopy(p["reference_solution"])
    drop = {"r11", "r21", "r31", "r41"}
    d["operations"] = [o for o in d["operations"] if o["id"] not in drop]
    from problems.checker import _check_distribution
    ok, detail = _check_distribution(p, p["check"], d)
    assert not ok and "at least 90%" in detail
