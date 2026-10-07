import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator

from conftest import circuit_of, compiled, codes, make_doc, node, operator_of, state_of, top_prob
from concepts import compile_document
from concepts.angles import pi


def L2(n, ops, c=0):
    return [(g["name"], tuple(g["targets"]), tuple(g.get("controls", ())), tuple(round(x, 6) for x in g.get("params", ())))
            for g in compiled(n, ops, c).gates]


def test_shake_lowers_to_h_per_target():
    assert L2(3, [node(1, "shake", [0, 2])]) == [("h", (0,), (), ()), ("h", (2,), (), ())]


def test_set_lowest_bit_is_targets_0():
    # value 6 = 0b110 -> bits 1 and 2 -> X on targets[1], targets[2]
    assert L2(3, [node(1, "set", [0, 1, 2], params={"value": 6})]) == [("x", (1,), (), ()), ("x", (2,), (), ())]


def test_set_bit_order_non_palindrome():
    # value 6 must give Qiskit label "110" (q2 q1 q0), not the naive "011"
    key, p = top_prob(state_of(3, [node(1, "set", [0, 1, 2], params={"value": 6})]))
    assert (key, round(p, 6)) == ("110", 1.0)


def test_set_uses_given_target_order_as_lsb_first():
    # targets [2,0] value 1 -> LSB is targets[0]=q2
    assert top_prob(state_of(3, [node(1, "set", [2, 0], params={"value": 1})]))[0] == "100"


def test_flip():
    assert L2(2, [node(1, "flip", [1])]) == [("x", (1,), (), ())]


@pytest.mark.parametrize("num,den,name", [(1, 1, "z"), (1, 2, "s"), (1, 4, "t"), (-1, 2, "sdg"), (-1, 4, "tdg")])
def test_phase_exact_names(num, den, name):
    assert L2(1, [node(1, "phase", [0], params={"angle": pi(num, den)})]) == [(name, (0,), (), ())]


def test_phase_other_angle_is_p_not_rz():
    g = compiled(1, [node(1, "phase", [0], params={"angle": pi(1, 3)})]).gates[0]
    assert g["name"] == "p"


def test_phase_rad_pi_is_exact_z():
    assert L2(1, [node(1, "phase", [0], params={"angle": {"rad": float(np.pi)}})])[0][0] == "z"


def test_phase_leaves_probabilities_unchanged():
    base = state_of(1, [node(1, "shake", [0])]).probabilities()
    after = state_of(1, [node(1, "shake", [0]), node(2, "phase", [0], params={"angle": pi(1, 4)})]).probabilities()
    assert np.allclose(base, after)


def test_phase_matches_p_exactly():
    for a, ref in [(pi(1), "z"), (pi(1, 2), "s"), (pi(1, 4), "t")]:
        qc = QuantumCircuit(1); qc.p(float(np.pi * a["pi"][0] / a["pi"][1]), 0)
        assert np.allclose(operator_of(1, [node(1, "phase", [0], params={"angle": a})]).data, Operator(qc).data)


def test_rotate_75_percent_needs_2pi_over_3():
    # RY(pi/3) -> P(1)=0.25 ; RY(2pi/3) -> P(1)=0.75
    p = lambda a: state_of(1, [node(1, "rotate", [0], params={"axis": "y", "angle": a})]).probabilities()[1]
    assert p(pi(1, 3)) == pytest.approx(0.25)
    assert p(pi(2, 3)) == pytest.approx(0.75)


def test_rotate_axes_lower_to_matching_gate():
    for ax in "xyz":
        assert L2(1, [node(1, "rotate", [0], params={"axis": ax, "angle": pi(1, 2)})])[0][0] == "r" + ax


def test_swap_moves_state():
    sv = state_of(3, [node(1, "set", [0], params={"value": 1}), node(2, "swap", [0, 2])])
    assert top_prob(sv)[0] == "100"


def test_swap_equals_three_cx():
    a = operator_of(3, [node(1, "swap", [0, 2])])
    b = QuantumCircuit(3); b.cx(0, 2); b.cx(2, 0); b.cx(0, 2)
    assert np.allclose(a.data, Operator(b).data)


def test_measure_and_reset_lower():
    r = L2(1, [node(1, "measure", [0], classical=[0]), node(2, "reset", [0])], c=1)
    assert [g[0] for g in r] == ["measure", "reset"]


def test_repeat_repeats_the_expansion():
    assert len(L2(1, [node(1, "flip", [0], repeat=3)])) == 3


# ── Control ──────────────────────────────────────────────────────────
def ctrl(i, controls, body):
    return {"id": f"op_{i}", "op": "control", "controls": controls, "targets": [], "body": body}


def body(op, targets, **kw):
    d = {"id": f"b_{op}", "op": op, "targets": targets}
    d.update(kw)
    return d


def test_control_flip_is_cx_ccx_mcx():
    assert L2(2, [ctrl(1, [0], body("flip", [1]))]) == [("x", (1,), (0,), ())]
    g3 = compiled(4, [ctrl(1, [0, 1, 2], body("flip", [3]))]).gates[0]
    assert g3["name"] == "x" and g3["controls"] == [0, 1, 2]


def test_control_phase_is_cp_not_crz():
    op = lambda th: operator_of(2, [ctrl(1, [0], body("phase", [1], params={"angle": {"rad": th}}))])
    cp = QuantumCircuit(2); cp.cp(0.7, 0, 1)
    crz = QuantumCircuit(2); crz.crz(0.7, 0, 1)
    got = op(0.7)
    assert np.allclose(got.data, Operator(cp).data)
    assert not got.equiv(Operator(crz))          # P != RZ once controlled


def test_control_phase_pi_is_cz():
    got = operator_of(2, [ctrl(1, [0], body("phase", [1], params={"angle": pi(1)}))])
    c = QuantumCircuit(2); c.cz(0, 1)
    assert np.allclose(got.data, Operator(c).data)


def test_control_of_s_uses_p_pi_over_2():
    got = operator_of(2, [ctrl(1, [0], body("phase", [1], params={"angle": pi(1, 2)}))])
    c = QuantumCircuit(2); c.cp(np.pi / 2, 0, 1)
    assert np.allclose(got.data, Operator(c).data)


def test_control_rotate_equals_cry():
    got = operator_of(2, [ctrl(1, [0], body("rotate", [1], params={"axis": "y", "angle": pi(1, 3)}))])
    c = QuantumCircuit(2); c.cry(np.pi / 3, 0, 1)
    assert np.allclose(got.data, Operator(c).data)


def test_control_swap_equals_cswap():
    got = operator_of(3, [ctrl(1, [0], body("swap", [1, 2]))])
    c = QuantumCircuit(3); c.cswap(0, 1, 2)
    assert np.allclose(got.data, Operator(c).data)


@pytest.mark.parametrize("k", [1, 2, 3])
def test_control_on_phase_matches_qiskit_control(k):
    from qiskit.circuit.library import PhaseGate
    n = k + 1
    got = operator_of(n, [ctrl(1, list(range(k)), body("phase", [k], params={"angle": pi(1, 5)}))])
    c = QuantumCircuit(n); c.append(PhaseGate(np.pi / 5).control(k), list(range(n)))
    assert np.allclose(got.data, Operator(c).data)


def test_control_on_shake_matches_ch():
    got = operator_of(2, [ctrl(1, [0], body("shake", [1]))])
    c = QuantumCircuit(2); c.ch(0, 1)
    assert np.allclose(got.data, Operator(c).data)


def test_control_around_measure_is_rejected():
    res = compile_document(make_doc(2, [ctrl(1, [0], body("measure", [1], classical=[0]))], 1))
    assert not res.ok and "E_PARAM" in codes(res)


def test_code_text_matches_circuit():
    """The copy-paste code builds exactly the circuit that ran."""
    from concepts.emit_qiskit import RUN_MARKER
    ops = [node(1, "shake", [0, 1, 2]), ctrl(2, [0], body("rotate", [1], params={"axis": "y", "angle": pi(1, 3)})),
           ctrl(3, [0, 1], body("flip", [2])), ctrl(4, [0], body("swap", [1, 2])),
           ctrl(5, [0], body("phase", [2], params={"angle": pi(1, 5)})), ctrl(6, [0], body("shake", [1])),
           node(7, "swap", [0, 2])]
    res = compiled(3, ops)
    src = res.qiskit_py.split(RUN_MARKER)[0]
    ns = {}
    exec(compile(src, "<gen>", "exec"), ns)
    assert np.allclose(Operator(ns["qc"]).data, Operator(circuit_of(3, ops)).data)
