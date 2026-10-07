"""Port of validate_concepts.py: the gate-level facts the concept design rests on.

The original script printed PASS/FAIL, including deliberate "expected FALSE" negatives.
Here every line is an assertion, and the negatives assert the negative.
Note: probabilities_dict() carries ~1e-37 dust entries, so single outcomes use the max key.
"""
import numpy as np
import pytest
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Instruction
from qiskit.circuit.library import QFTGate
from qiskit.quantum_info import Operator, Statevector
from qiskit_aer import AerSimulator


def eq(a, b, up_to_phase=False):
    A, B = Operator(a), Operator(b)
    return A.equiv(B) if up_to_phase else np.allclose(A.data, B.data)


@pytest.mark.parametrize("ang,g", [(np.pi, "z"), (np.pi / 2, "s"), (np.pi / 4, "t")])
def test_phase_exact_names(ang, g):
    a = QuantumCircuit(1); a.p(ang, 0)
    b = QuantumCircuit(1); getattr(b, g)(0)
    assert eq(a, b)


def test_phase_leaves_probabilities_unchanged():
    a = QuantumCircuit(1); a.t(0)
    sv = Statevector.from_label("+")
    assert np.allclose(sv.probabilities(), sv.evolve(a).probabilities())


def test_p_vs_rz_equal_only_up_to_global_phase():
    a = QuantumCircuit(1); a.p(0.7, 0)
    b = QuantumCircuit(1); b.rz(0.7, 0)
    assert not eq(a, b)
    assert eq(a, b, True)


def test_control_of_p_is_not_control_of_rz():
    a = QuantumCircuit(2); a.cp(0.7, 0, 1)
    b = QuantumCircuit(2); b.crz(0.7, 0, 1)
    assert not eq(a, b, True)          # global phase becomes relative phase under control


def test_rotate_75_percent():
    p1 = lambda th: (lambda c: Statevector(c).probabilities()[1])((lambda c: (c.ry(th, 0), c)[1])(QuantumCircuit(1)))
    assert np.isclose(p1(np.pi / 3), 0.25)
    assert np.isclose(p1(2 * np.pi / 3), 0.75)


def test_control_wrappers():
    a = QuantumCircuit(2); a.cp(np.pi, 0, 1)
    b = QuantumCircuit(2); b.cz(0, 1)
    assert eq(a, b)
    r = QuantumCircuit(1); r.ry(np.pi / 3, 0)
    ca = QuantumCircuit(2); ca.append(r.to_gate().control(1), [0, 1])
    cb = QuantumCircuit(2); cb.cry(np.pi / 3, 0, 1)
    assert eq(ca, cb)


def test_swap_is_three_cx():
    a = QuantumCircuit(3); a.swap(0, 2)
    b = QuantumCircuit(3); b.cx(0, 2); b.cx(2, 0); b.cx(0, 2)
    assert eq(a, b)


def test_manual_qft_equals_qftgate_and_inverse_cancels():
    n = 3
    m = QuantumCircuit(n)
    for j in reversed(range(n)):
        m.h(j)
        for k in reversed(range(j)):
            m.cp(np.pi / 2 ** (j - k), k, j)
    m.swap(0, n - 1)
    ref = QuantumCircuit(n); ref.append(QFTGate(n), range(n))
    assert eq(m, ref, True)
    inv = QuantumCircuit(n); inv.compose(ref, inplace=True); inv.compose(ref.inverse(), inplace=True)
    assert eq(inv, QuantumCircuit(n))


def test_bit_order_is_little_endian():
    c = QuantumCircuit(3); c.x(0); c.x(2)
    assert Statevector(c).probabilities_dict() == {"101": 1.0}       # palindrome: order-agnostic
    c = QuantumCircuit(3); c.x(0); c.x(1)                            # naive left-to-right reading of "110"
    got = max(Statevector(c).probabilities_dict().items(), key=lambda kv: kv[1])[0]
    assert got == "011"                                              # NOT "110": Qiskit is little-endian


def _compare5(qc):
    qc.x(1); qc.mcx([0, 1, 2], 3); qc.x(1)


def test_compare_five_for_all_inputs():
    for v in range(8):
        qc = QuantumCircuit(4)
        for i in range(3):
            if (v >> i) & 1:
                qc.x(i)
        _compare5(qc)
        d = Statevector(qc).probabilities_dict()
        flag = int(max(d, key=d.get)[0])
        assert flag == (v == 5)


def test_compare_phase_uncompute_flips_five_only():
    qc = QuantumCircuit(4)
    _compare5(qc); qc.z(3); _compare5(qc)
    diag = np.diag(Operator(qc).data)
    expected = np.array([(-1 if (i & 7) == 5 and not (i >> 3) else 1) for i in range(16)])
    assert np.allclose(diag[:8], expected[:8]) and np.allclose(Operator(qc).data, np.diag(diag))


def test_grover_amplifies_five():
    g = QuantumCircuit(4, 3); g.h(range(3))
    for _ in range(2):
        _compare5(g); g.z(3); _compare5(g)
        g.h(range(3)); g.x(range(3)); g.h(2); g.ccx(0, 1, 2); g.h(2); g.x(range(3)); g.h(range(3))
    g.measure(range(3), range(3))
    counts = AerSimulator().run(transpile(g, AerSimulator()), shots=4000, seed_simulator=1).result().get_counts()
    assert counts.get("101", 0) / 4000 > 0.9


def test_add_three_mod_eight_is_a_permutation():
    perm = np.zeros((8, 8))
    for v in range(8):
        perm[(v + 3) % 8, v] = 1
    assert np.allclose(perm @ perm.T, np.eye(8))


def test_add_without_modulus_overflows():
    assert 5 + 3 == 8 and 8 >= 2 ** 3          # 5+3 does not fit in 3 qubits


def test_uncompute_needs_a_unitary_block():
    b = QuantumCircuit(1, 1); b.h(0); b.measure(0, 0)
    with pytest.raises(Exception):
        b.inverse()


def test_teleportation_with_if_test():
    theta = 1.1
    t = QuantumCircuit(3, 3)
    t.ry(theta, 0); t.h(1); t.cx(1, 2); t.cx(0, 1); t.h(0)
    t.measure(0, 0); t.measure(1, 1)
    with t.if_test((t.clbits[1], 1)): t.x(2)
    with t.if_test((t.clbits[0], 1)): t.z(2)
    t.measure(2, 2)
    c = AerSimulator().run(transpile(t, AerSimulator()), shots=20000, seed_simulator=7).result().get_counts()
    p1 = sum(v for k, v in c.items() if k[0] == "1") / 20000
    assert abs(p1 - np.sin(theta / 2) ** 2) < 0.02


def test_c_if_is_gone_in_qiskit_2():
    assert not hasattr(Instruction, "c_if")


def test_cz_alone_on_zero_creates_no_entanglement():
    c = QuantumCircuit(2); c.cz(0, 1)
    assert Statevector(c).equiv(Statevector.from_label("00"))
