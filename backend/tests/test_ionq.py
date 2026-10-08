import numpy as np
import pytest
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import PhaseGate
from qiskit.quantum_info import Operator
from qiskit_aer import AerSimulator

from conftest import circuit_of, compiled, make_doc, node, warn_codes
from concepts import compile_document
from concepts.angles import pi
from concepts.emit_qiskit import build_circuit
from concepts.ionq_lower import BackendUnsupported, lower_for_ionq, rewritten_lowered
from test_composites import teleport_doc


def ionq_to_circuit(ionq):
    """Interpret an IonQ qis circuit with Qiskit so it can be compared to the L2 operator."""
    qc = QuantumCircuit(ionq["qubits"])
    for g in ionq["circuit"]:
        n, t = g["gate"], g.get("target")
        if n in ("h", "x", "y", "z", "s", "t"):
            getattr(qc, n)(t)
        elif n == "si": qc.sdg(t)
        elif n == "ti": qc.tdg(t)
        elif n in ("rx", "ry", "rz"): getattr(qc, n)(g["rotation"], t)
        elif n == "cnot": qc.cx(g["control"], t)
        elif n == "mcx": qc.mcx(g["controls"], t)
        else: raise AssertionError(f"unexpected IonQ gate {g}")
    return qc


def uni(qc):
    return Operator(qc.remove_final_measurements(inplace=False))


def ctrl(i, controls, b):
    return {"id": f"op_{i}", "op": "control", "controls": controls, "body": b}


CASES = {
    "bell": (2, [node(1, "shake", [0]), node(2, "entangle", [0, 1])]),
    "cz": (2, [node(1, "entangle", [0, 1], params={"style": "cz"})]),
    "swap": (3, [node(1, "swap", [0, 2])]),
    "ccx": (3, [ctrl(1, [0, 1], {"id": "b", "op": "flip", "targets": [2]})]),
    "mcx4": (5, [ctrl(1, [0, 1, 2, 3], {"id": "b", "op": "flip", "targets": [4]})]),
    "cp": (2, [ctrl(1, [0], {"id": "b", "op": "phase", "targets": [1], "params": {"angle": pi(1, 3)}})]),
    "crx": (2, [ctrl(1, [0], {"id": "b", "op": "rotate", "targets": [1], "params": {"axis": "x", "angle": pi(2, 5)}})]),
    "cry": (2, [ctrl(1, [0], {"id": "b", "op": "rotate", "targets": [1], "params": {"axis": "y", "angle": pi(1, 3)}})]),
    "crz": (2, [ctrl(1, [0], {"id": "b", "op": "rotate", "targets": [1], "params": {"axis": "z", "angle": pi(1, 3)}})]),
    "ch": (2, [ctrl(1, [0], {"id": "b", "op": "shake", "targets": [1]})]),
    "cswap": (3, [ctrl(1, [0], {"id": "b", "op": "swap", "targets": [1, 2]})]),
    "grover": (4, [node(1, "shake", [0, 1, 2]), node(2, "compare", [0, 1, 2], ancillas=[3], params={"value": 5}),
                   node(3, "mark", [], params={"via": "op_2"}), node(4, "boost", [0, 1, 2], repeat=2)]),
    "fourier": (3, [node(1, "fourier", [0, 1, 2])]),
    "add": (3, [node(1, "add", [0, 1, 2], params={"value": 3, "modulus": 8})]),
    "phases": (1, [node(1, "phase", [0], params={"angle": pi(1, 8)}), node(2, "phase", [0], params={"angle": pi(-1, 2)})]),
}


@pytest.mark.parametrize("name", list(CASES))
def test_ionq_lowering_matches_the_l2_operator(name):
    n, ops = CASES[name]
    res = compile_document(make_doc(n, ops), backend="ionq")
    assert res.ok and res.ionq, [w.message for w in res.warnings]
    assert uni(ionq_to_circuit(res.ionq)).equiv(uni(build_circuit(res.lowered)))      # up to global phase


def test_ionq_src_index_points_back_at_l2_gates():
    n, ops = CASES["grover"]
    res = compile_document(make_doc(n, ops), backend="ionq")
    assert len(res.ionq_src) == len(res.ionq["circuit"])
    assert all(0 <= i < len(res.gates) for i in res.ionq_src)


def test_teleport_ionq_rewrite_matches_aer():
    rng = np.random.default_rng(3)
    for theta in rng.uniform(0.2, 2.9, size=3):
        ops = teleport_doc(float(theta))
        doc = make_doc(3, ops, 3)
        res = compile_document(doc, backend="ionq")
        assert res.ok and res.ionq, [w.message for w in res.warnings]
        orig = circuit_of(3, ops, 3)
        rewritten = build_circuit(rewritten_lowered(res.lowered))
        assert "if_else" in orig.count_ops() and "if_else" not in rewritten.count_ops()
        sim = AerSimulator()
        shots = 40000
        a = sim.run(transpile(orig, sim), shots=shots, seed_simulator=11).result().get_counts()
        b = sim.run(transpile(rewritten, sim), shots=shots, seed_simulator=12).result().get_counts()
        keys = set(a) | set(b)
        tv = 0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys) / shots
        assert tv < 0.02, (theta, tv)
        # and q2 reproduces the sent state
        p1 = sum(v for k, v in b.items() if k[0] == "1") / shots
        assert abs(p1 - np.sin(theta / 2) ** 2) < 0.02


def test_ionq_circuit_has_no_measure_and_no_conditions():
    res = compile_document(make_doc(3, teleport_doc(0.7), 3), backend="ionq")
    assert all(g["gate"] != "measure" for g in res.ionq["circuit"])
    assert any(g["gate"] == "cnot" for g in res.ionq["circuit"])


def test_condition_on_zero_wraps_the_control_in_x():
    ops = [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]),
           {"id": "op_3", "op": "correct", "condition": {"clbit": 0, "equals": 0},
            "body": {"id": "b", "op": "flip", "targets": [1]}}]
    res = compile_document(make_doc(2, ops, 1), backend="ionq")
    names = [g["gate"] for g in res.ionq["circuit"]]
    assert names == ["h", "x", "cnot", "x"]


def test_refuses_when_measured_qubit_is_reused():
    ops = [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]), node(3, "flip", [0])]
    res = compile_document(make_doc(1, ops, 1), backend="ionq")
    assert res.ok and res.ionq is None and "W_BACKEND_UNSUPPORTED" in warn_codes(res)
    assert "measured" in [w for w in res.warnings if w.code == "W_BACKEND_UNSUPPORTED"][0].message


def test_refuses_correct_acting_on_its_own_measured_qubit():
    ops = [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]),
           {"id": "op_3", "op": "correct", "condition": {"clbit": 0, "equals": 1},
            "body": {"id": "b", "op": "flip", "targets": [0]}}]
    res = compile_document(make_doc(1, ops, 1), backend="ionq")
    assert res.ionq is None and "W_BACKEND_UNSUPPORTED" in warn_codes(res)


def test_aer_still_runs_what_ionq_refuses():
    ops = [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]), node(3, "reset", [0]),
           node(4, "measure", [0], classical=[1])]
    qc = circuit_of(1, ops, 2)
    sim = AerSimulator()
    c = sim.run(transpile(qc, sim), shots=500, seed_simulator=5).result().get_counts()
    assert all(k[0] == "0" for k in c)           # second measurement (clbit 1) after Reset is always 0
