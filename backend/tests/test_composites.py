import itertools

import numpy as np
import pytest
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import QFTGate
from qiskit.quantum_info import Operator, Statevector
from qiskit_aer import AerSimulator

from conftest import circuit_of, compiled, make_doc, node, operator_of, state_of, top_prob
from concepts.angles import pi


def basis_run(n, prep_qubits_value, ops, c=0):
    """Prepare a basis input (LSB = q0..), run ops, return (label, prob)."""
    prep = [node(900 + i, "flip", [q]) for i, q in enumerate(prep_qubits_value)]
    return top_prob(state_of(n, prep + ops, c))


def bit(label, q):          # Qiskit label is MSB-left: q0 is the last char
    return int(label[::-1][q])


# ── Entangle ─────────────────────────────────────────────────────────
def test_entangle_after_shake_is_bell():
    sv = state_of(2, [node(1, "shake", [0]), node(2, "entangle", [0, 1])])
    assert sv.equiv(Statevector([1, 0, 0, 1]) / np.sqrt(2))


def test_entangle_cz_style_is_cz():
    got = operator_of(2, [node(1, "entangle", [0, 1], params={"style": "cz"})])
    c = QuantumCircuit(2); c.cz(0, 1)
    assert np.allclose(got.data, Operator(c).data)


def test_entangle_expands_to_control_flip():
    assert compiled(2, [node(1, "entangle", [0, 1])]).gates == [{"name": "x", "targets": [1], "controls": [0]}]


# ── Encode ───────────────────────────────────────────────────────────
def test_encode_basis_equals_set():
    a = state_of(3, [node(1, "encode", [0, 1, 2], params={"method": "basis", "data": 5})])
    assert top_prob(a)[0] == "101"


def test_encode_angle_arcsin_sqrt_gives_probability():
    sv = state_of(2, [node(1, "encode", [0, 1], params={"method": "angle", "scaling": "arcsin_sqrt", "data": [0.2, 0.8]})])
    p = [sum(pr for i, pr in enumerate(sv.probabilities()) if (i >> q) & 1) for q in range(2)]
    assert p == pytest.approx([0.2, 0.8], abs=1e-9)


def test_encode_angle_pi_x():
    sv = state_of(1, [node(1, "encode", [0], params={"method": "angle", "scaling": "pi_x", "data": [0.5]})])
    assert sv.probabilities()[1] == pytest.approx(0.5)      # RY(pi/2)


# ── Compare ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("operator", ["eq", "neq"])
def test_compare_flags_for_all_inputs(operator):
    """All 2^3 inputs: flag (q3) == (register == 5) for eq, the opposite for neq."""
    cmp_ = node(1, "compare", [0, 1, 2], ancillas=[3], params={"operator": operator, "value": 5})
    for v in range(8):
        prep = [q for q in range(3) if (v >> q) & 1]
        label, p = basis_run(4, prep, [cmp_])
        assert p == pytest.approx(1.0)
        want = (v == 5) if operator == "eq" else (v != 5)
        assert bit(label, 3) == int(want), (v, label)
        assert sum(bit(label, q) << q for q in range(3)) == v          # register untouched


# ── Mark ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value", [0, 3, 5, 7])
def test_mark_direct_flips_only_that_state(value):
    ops = [node(1, "shake", [0, 1, 2]), node(2, "mark", [0, 1, 2], params={"value": value})]
    sv = state_of(3, ops).data * np.sqrt(8)
    want = np.ones(8, dtype=complex); want[value] = -1
    assert np.allclose(sv, want)


def test_mark_via_compare_flips_sign_of_five_only_and_restores_ancilla():
    ops = [node(1, "shake", [0, 1, 2]),
           node(2, "compare", [0, 1, 2], ancillas=[3], params={"value": 5}),
           node(3, "mark", [], params={"via": "op_2"})]
    sv = state_of(4, ops).data
    want = np.zeros(16, dtype=complex); want[:8] = 1 / np.sqrt(8); want[5] *= -1
    assert np.allclose(sv, want)           # ancilla back to |0>, only |5> has a minus sign


def test_compare_phase_uncompute_is_a_phase_oracle():
    ops = [node(1, "shake", [0, 1, 2]),
           node(2, "compare", [0, 1, 2], ancillas=[3], params={"value": 5}),
           node(3, "phase", [3], params={"angle": pi(1)}),
           node(4, "uncompute", [], ref="op_2")]
    sv = state_of(4, ops).data
    want = np.zeros(16, dtype=complex); want[:8] = 1 / np.sqrt(8); want[5] *= -1
    assert np.allclose(sv, want)


# ── Boost / Grover ───────────────────────────────────────────────────
def test_grover_compare_mark_uncompute_boost_finds_five():
    ops = [node(1, "shake", [0, 1, 2])]
    for k in range(2):
        ops += [node(10 + k, "compare", [0, 1, 2], ancillas=[3], params={"value": 5}),
                node(20 + k, "phase", [3], params={"angle": pi(1)}),
                node(30 + k, "uncompute", [], ref=f"op_{10 + k}"),
                node(40 + k, "boost", [0, 1, 2])]
    ops.append(node(50, "measure", [0, 1, 2], classical=[0, 1, 2]))
    qc = circuit_of(4, ops, 3)
    counts = AerSimulator().run(transpile(qc, AerSimulator()), shots=4000, seed_simulator=1).result().get_counts()
    assert counts.get("101", 0) / 4000 > 0.9


def test_boost_repeat_equals_two_nodes():
    one = [node(1, "shake", [0, 1, 2]), node(2, "mark", [0, 1, 2], params={"value": 5}), node(3, "boost", [0, 1, 2], repeat=2)]
    two = one[:2] + [node(3, "boost", [0, 1, 2]), node(4, "boost", [0, 1, 2])]
    assert np.allclose(operator_of(3, one).data, operator_of(3, two).data)


# ── Fourier / Add ────────────────────────────────────────────────────
@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_fourier_equals_qft_gate_up_to_global_phase(n):
    ref = QuantumCircuit(n); ref.append(QFTGate(n), range(n))
    assert operator_of(n, [node(1, "fourier", list(range(n)))]).equiv(Operator(ref))


def test_forward_then_inverse_is_identity():
    ops = [node(1, "fourier", [0, 1, 2]), node(2, "fourier", [0, 1, 2], params={"inverse": True})]
    assert np.allclose(operator_of(3, ops).data, np.eye(8))


def test_fourier_without_swaps_is_the_bit_reversed_qft():
    a = operator_of(3, [node(1, "fourier", [0, 1, 2], params={"swaps": False})])
    swap = QuantumCircuit(3); swap.swap(0, 2)
    b = operator_of(3, [node(1, "fourier", [0, 1, 2]), node(2, "swap", [0, 2])])
    assert np.allclose(a.data, b.data)


@pytest.mark.parametrize("n,c", [(2, 1), (3, 3), (3, 5), (3, 0), (4, 11)])
def test_add_constant_mod_2n_for_all_inputs(n, c):
    ops = [node(1, "add", list(range(n)), params={"value": c, "modulus": 2 ** n})]
    for v in range(2 ** n):
        label, p = basis_run(n, [q for q in range(n) if (v >> q) & 1], ops)
        assert p == pytest.approx(1.0)
        assert int(label, 2) == (v + c) % (2 ** n), (v, c, label)


def test_add_is_reversible():
    u = operator_of(3, [node(1, "add", [0, 1, 2], params={"value": 3, "modulus": 8})]).data
    assert np.allclose(u @ u.conj().T, np.eye(8))


# ── Uncompute ────────────────────────────────────────────────────────
def test_uncompute_is_the_dagger():
    ops = [node(1, "shake", [0]), node(2, "fourier", [0, 1]), node(3, "uncompute", [], ref="op_2")]
    a = operator_of(2, ops)
    b = operator_of(2, [node(1, "shake", [0])])
    assert np.allclose(a.data, b.data)


# ── Correct (teleportation) ──────────────────────────────────────────
def teleport_doc(theta):
    def correct(i, clbit, body_op, tgt, **kw):
        return {"id": f"op_{i}", "op": "correct", "targets": [], "condition": {"clbit": clbit, "equals": 1},
                "body": {"id": f"op_{i}b", "op": body_op, "targets": [tgt], **kw}}
    return [node(1, "rotate", [0], params={"axis": "y", "angle": {"rad": theta}}),
            node(2, "shake", [1]), node(3, "entangle", [1, 2]),
            node(4, "entangle", [0, 1]), node(5, "shake", [0]),
            node(6, "measure", [0, 1], classical=[0, 1]),
            correct(7, 1, "flip", 2), correct(8, 0, "phase", 2, params={"angle": pi(1)}),
            node(9, "measure", [2], classical=[2])]


def test_teleportation_with_correct_reproduces_the_state():
    theta = 1.1
    qc = circuit_of(3, teleport_doc(theta), 3)
    assert "if_else" in qc.count_ops()
    c = AerSimulator().run(transpile(qc, AerSimulator()), shots=20000, seed_simulator=7).result().get_counts()
    p1 = sum(v for k, v in c.items() if k[0] == "1") / 20000
    assert abs(p1 - np.sin(theta / 2) ** 2) < 0.02


def test_correct_uses_if_test_not_c_if():
    res = compiled(3, teleport_doc(0.5), 3)
    assert "if_test" in res.qiskit_py and "c_if" not in res.qiskit_py
    qc = circuit_of(3, teleport_doc(0.5), 3)
    # a legacy c_if would hang a condition on a plain gate; if_test lives only on if_else blocks
    assert all(i.operation.name == "if_else" or getattr(i.operation, "condition", None) is None for i in qc.data)


# ── plan section 7: "Under Control" and "Unit" rows ───────────────────
def ctrl_wrap(control_qubit, body):
    return {"id": "ctl", "op": "control", "controls": [control_qubit], "body": body}


BODIES = {
    "shake": {"id": "b", "op": "shake", "targets": [0, 1]},
    "flip": {"id": "b", "op": "flip", "targets": [2]},
    "set": {"id": "b", "op": "set", "targets": [0, 1, 2], "params": {"value": 5}},
    "phase_pi3": {"id": "b", "op": "phase", "targets": [1], "params": {"angle": pi(1, 3)}},
    "phase_pi": {"id": "b", "op": "phase", "targets": [1], "params": {"angle": pi(1)}},
    "rotate_x": {"id": "b", "op": "rotate", "targets": [0], "params": {"axis": "x", "angle": pi(1, 3)}},
    "rotate_y": {"id": "b", "op": "rotate", "targets": [0], "params": {"axis": "y", "angle": pi(2, 5)}},
    "rotate_z": {"id": "b", "op": "rotate", "targets": [0], "params": {"axis": "z", "angle": pi(1, 7)}},
    "swap": {"id": "b", "op": "swap", "targets": [0, 2]},
    "entangle_cx": {"id": "b", "op": "entangle", "targets": [0, 1]},
    "entangle_cz": {"id": "b", "op": "entangle", "targets": [0, 1], "params": {"style": "cz"}},
    "compare_neq": {"id": "b", "op": "compare", "targets": [0, 1, 2], "ancillas": [3], "params": {"operator": "neq", "value": 5}},
    "mark": {"id": "b", "op": "mark", "targets": [0, 1, 2], "params": {"value": 6}},
    "boost": {"id": "b", "op": "boost", "targets": [0, 1, 2]},
    "fourier": {"id": "b", "op": "fourier", "targets": [0, 1, 2]},
    "fourier_inv": {"id": "b", "op": "fourier", "targets": [0, 1, 2], "params": {"inverse": True}},
    "add": {"id": "b", "op": "add", "targets": [0, 1, 2], "params": {"value": 3, "modulus": 8}},
}


@pytest.mark.parametrize("name", list(BODIES))
def test_each_unitary_concept_under_control_equals_qiskit_control(name):
    body = BODIES[name]
    need = 4                                   # body uses q0..q3, the control is q4
    body_qc = circuit_of(need, [body])
    ref = QuantumCircuit(need + 1)
    ref.append(body_qc.to_gate().control(1), [need, 0, 1, 2, 3])
    got = operator_of(need + 1, [ctrl_wrap(need, body)])
    # exact when the body has no global phase of its own, otherwise up to nothing but that phase
    assert got.equiv(Operator(ref)) and np.allclose(got.data, Operator(ref).data)


def test_set_exhaustive_for_every_value():
    for v in range(8):
        sv = state_of(3, [node(1, "set", [0, 1, 2], params={"value": v})])
        assert top_prob(sv)[0] == format(v, "03b")


def test_flip_exhaustive_toggles_each_basis_state():
    for v in range(4):
        prep = [node(10 + q, "flip", [q]) for q in range(2) if (v >> q) & 1]
        base = state_of(2, prep)
        after = state_of(2, prep + [node(99, "flip", [0, 1])])
        assert top_prob(after)[0] == format(v ^ 0b11, "02b")


def l2(ops, n, c=0):
    return [(g["name"], tuple(g["targets"]), tuple(g.get("controls", ()))) for g in compiled(n, ops, c).gates]


def test_unit_compare_gate_list_for_five():
    got = l2([node(1, "compare", [0, 1, 2], ancillas=[3], params={"value": 5})], 4)
    assert got == [("x", (1,), ()), ("x", (3,), (0, 1, 2)), ("x", (1,), ())]


def test_unit_mark_direct_gate_list():
    got = l2([node(1, "mark", [0, 1], params={"value": 1})], 2)
    # value 1 = 0b01: q1 is 0 -> X(q1); CZ; X(q1)
    assert got == [("x", (1,), ()), ("z", (1,), (0,)), ("x", (1,), ())]


def test_unit_boost_two_qubits_is_h_x_cz_x_h():
    got = l2([node(1, "boost", [0, 1])], 2)
    assert got == [("h", (0,), ()), ("h", (1,), ()), ("x", (0,), ()), ("x", (1,), ()), ("z", (1,), (0,)),
                   ("x", (0,), ()), ("x", (1,), ()), ("h", (0,), ()), ("h", (1,), ())]


def test_unit_fourier_two_qubits():
    got = l2([node(1, "fourier", [0, 1])], 2)
    assert got == [("h", (1,), ()), ("p", (1,), (0,)), ("h", (0,), ()), ("swap", (0, 1), ())]


def test_unit_entangle_cz_is_controlled_z():
    assert l2([node(1, "entangle", [0, 1], params={"style": "cz"})], 2) == [("z", (1,), (0,))]
