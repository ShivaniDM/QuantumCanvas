"""One failing case (and where useful one passing case) per error / warning code."""
import pytest

from conftest import codes, make_doc, node, warn_codes
from concepts import compile_document
from concepts.angles import pi


def run(n, ops, c=0):
    return compile_document(make_doc(n, ops, c))


def test_E_QUBIT_RANGE():
    assert "E_QUBIT_RANGE" in codes(run(2, [node(1, "flip", [2])]))
    assert run(2, [node(1, "flip", [1])]).ok


def test_E_CLBIT_RANGE():
    assert "E_CLBIT_RANGE" in codes(run(1, [node(1, "measure", [0], classical=[1])], 1))


def test_E_OVERLAP_within_node():
    assert "E_OVERLAP" in codes(run(2, [node(1, "swap", [0, 0])]))
    assert "E_OVERLAP" in codes(run(2, [{"id": "c", "op": "control", "controls": [0],
                                         "body": {"id": "b", "op": "flip", "targets": [0]}}]))


def test_E_SET_NOT_FRESH():
    r = run(2, [node(1, "flip", [0]), node(2, "set", [0, 1], params={"value": 1})])
    assert "E_SET_NOT_FRESH" in codes(r)
    # a Reset makes it legal again; a measured qubit also needs a Reset
    ok = run(2, [node(1, "flip", [0]), node(2, "reset", [0]), node(3, "set", [0, 1], params={"value": 1})])
    assert ok.ok
    m = run(2, [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]), node(3, "set", [0], params={"value": 1})], 1)
    assert "E_SET_NOT_FRESH" in codes(m)


def test_E_SET_value_must_fit():
    assert "E_PARAM" in codes(run(2, [node(1, "set", [0, 1], params={"value": 4})]))


def test_E_ANCILLA_DIRTY():
    cmp_ = lambda i: node(i, "compare", [0, 1], ancillas=[2], params={"value": 1})
    assert "E_ANCILLA_DIRTY" in codes(run(3, [cmp_(1), cmp_(2)]))                    # ancilla still holds the first answer
    assert run(3, [cmp_(1), node(2, "uncompute", [], ref="op_1"), cmp_(3)]).ok        # uncomputed -> clean again
    assert "E_ANCILLA_DIRTY" in codes(run(3, [node(1, "flip", [2]), cmp_(2)]))


def test_E_UNCOMPUTE_NONUNITARY():
    ops = [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]), node(3, "uncompute", [], ref="op_2")]
    assert "E_UNCOMPUTE_NONUNITARY" in codes(run(1, ops, 1))


def test_uncompute_rejects_measure():
    ops = [node(1, "reset", [0]), node(2, "uncompute", [], ref="op_1")]
    assert "E_UNCOMPUTE_NONUNITARY" in codes(run(1, ops))


def test_E_UNCOMPUTE_INTERFERENCE():
    cmp_ = node(1, "compare", [0, 1], ancillas=[2], params={"value": 1})
    bad = [cmp_, node(2, "flip", [0]), node(3, "uncompute", [], ref="op_1")]
    assert "E_UNCOMPUTE_INTERFERENCE" in codes(run(3, bad))
    good = [cmp_, node(2, "phase", [2], params={"angle": pi(1)}), node(3, "mark", [0, 1], params={"value": 2}),
            node(4, "uncompute", [], ref="op_1")]
    assert run(3, good).ok          # only diagonal (phase-type) steps in between


def test_E_UNCOMPUTE_REF():
    assert "E_UNCOMPUTE_REF" in codes(run(1, [node(1, "uncompute", [], ref="nope")]))
    after = [node(1, "uncompute", [], ref="op_2"), node(2, "flip", [0])]
    assert "E_UNCOMPUTE_REF" in codes(run(1, after))


def test_E_ADD_OVERFLOW_requires_modulus():
    assert "E_ADD_OVERFLOW" in codes(run(3, [node(1, "add", [0, 1, 2], params={"value": 3})]))
    assert "E_ADD_OVERFLOW" in codes(run(3, [node(1, "add", [0, 1, 2], params={"value": 3, "modulus": 7})]))
    assert run(3, [node(1, "add", [0, 1, 2], params={"value": 3, "modulus": 8})]).ok


def test_add_requires_modulus():
    # regression name from the plan: 5 + 3 = 8 does not fit 3 qubits without a modulus
    r = run(3, [node(1, "add", [0, 1, 2], params={"value": 3})])
    assert not r.ok and "modulus" in r.errors[0].message.lower()


def test_E_COND_UNWRITTEN():
    corr = {"id": "c", "op": "correct", "condition": {"clbit": 0, "equals": 1},
            "body": {"id": "b", "op": "flip", "targets": [1]}}
    assert "E_COND_UNWRITTEN" in codes(run(2, [corr], 1))
    assert run(2, [node(1, "measure", [0], classical=[0]), corr], 1).ok


def test_E_ENCODE_SCALE():
    assert "E_ENCODE_SCALE" in codes(run(1, [node(1, "encode", [0], params={"method": "angle", "data": [0.5]})]))
    bad_range = node(1, "encode", [0], params={"method": "angle", "scaling": "arcsin_sqrt", "data": [1.5]})
    assert "E_ENCODE_SCALE" in codes(run(1, [bad_range]))


def test_W_NOOP_ENTANGLE():
    assert "W_NOOP_ENTANGLE" in warn_codes(run(2, [node(1, "entangle", [0, 1])]))
    assert "W_NOOP_ENTANGLE" in warn_codes(run(2, [node(1, "entangle", [0, 1], params={"style": "cz"})]))
    ok = run(2, [node(1, "shake", [0]), node(2, "entangle", [0, 1])])
    assert ok.ok and "W_NOOP_ENTANGLE" not in warn_codes(ok)
    assert "W_NOOP_ENTANGLE" in warn_codes(run(2, [node(1, "shake", [1]), node(2, "entangle", [0, 1])]))


def test_cz_alone_on_zero_is_a_noop_but_still_compiles():
    r = run(2, [node(1, "entangle", [0, 1], params={"style": "cz"})])
    assert r.ok


def test_E_DUP_ID_and_unknown_op_and_schema():
    assert "E_DUP_ID" in codes(run(1, [node(1, "flip", [0]), node(1, "flip", [0])]))
    assert "E_UNKNOWN_OP" in codes(run(1, [node(1, "teleport", [0])]))
    assert "E_SCHEMA" in codes(compile_document({"operations": "nope"}))


def test_E_PARAM_cases():
    bad = [
        node(1, "rotate", [0], params={"axis": "q", "angle": pi(1)}),
        node(1, "phase", [0], params={"angle": "pi/2"}),            # strings are never evaluated
        node(1, "phase", [0], params={"angle": {"pi": [1, 0]}}),
        node(1, "compare", [0], ancillas=[1], params={"operator": "lt", "value": 0}),
        node(1, "reset", [0, 1]),
        node(1, "swap", [0]),
        node(1, "measure", [0, 1], classical=[0]),
        node(1, "mark", [0, 1], params={"value": 1, "via": "x"}),
        node(1, "set", [0], params={"value": -1}),
    ]
    for b in bad:
        r = run(2, [b], 2)
        assert not r.ok and r.errors[0].code in ("E_PARAM", "E_UNCOMPUTE_REF"), (b, [e.code for e in r.errors])


def test_messages_are_plain_language_not_stack_traces():
    r = run(2, [node(1, "flip", [5])])
    msg = r.errors[0].message
    assert "Traceback" not in msg and "q" in msg or "qubit" in msg
    assert r.errors[0].hint


def test_W_BACKEND_UNSUPPORTED_for_reset_on_ionq():
    ops = [node(1, "shake", [0]), node(2, "measure", [0], classical=[0]), node(3, "reset", [0])]
    r = compile_document(make_doc(1, ops, 1), backend="ionq")
    assert r.ok and r.ionq is None and "W_BACKEND_UNSUPPORTED" in warn_codes(r)
