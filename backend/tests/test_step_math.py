"""Math tab (exact kets / matrices) and the per-step "?" explanation."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from explain import llm, step as step_mod
from mathlayer import analyze_document
from mathlayer.notation import fmt_complex, fmt_real, ket_string, step_math, terms_of


def nd(i, op, t, params=None, classical=None):
    return {"id": i, "op": op, "targets": t, "params": params or {}, "classical": classical or []}


def doc(ops, n=2, nc=0):
    return {"version": "0.3", "qubits": n, "classical_bits": nc, "operations": ops}


@pytest.fixture(autouse=True)
def _fresh():
    step_mod._cache.clear()
    llm.budget_reset()


def test_numbers_are_written_exactly():
    assert [fmt_real(x) for x in (0, 1, -0.5, 2 ** -.5, 1 / (2 * 2 ** .5), 2 ** .5, 0.75, 3 ** .5 / 2)] == \
        ["0", "1", "−1/2", "1/√2", "1/(2√2)", "√2", "3/4", "√3/2"]
    assert fmt_complex(0.5 + 0.5j) == "1/2 + i/2" and fmt_complex(1j * 2 ** -.5) == "i/√2" and fmt_complex(-1j) == "−i"


def test_bell_pair_in_dirac_notation():
    m = step_math(doc([nd("a", "shake", [0]), nd("b", "entangle", [0, 1])]))
    assert m["initial"]["branches"][0]["ket"] == "|00⟩"
    assert m["steps"][0]["after"]["branches"][0]["ket"] == "(|00⟩ + |01⟩)/√2"
    assert m["steps"][1]["after"]["branches"][0]["ket"] == "(|00⟩ + |11⟩)/√2"
    assert m["steps"][1]["matrix"] == [["1", "0", "0", "0"], ["0", "0", "0", "1"], ["0", "0", "1", "0"], ["0", "1", "0", "0"]]
    assert {"from": "01", "to": "|11⟩"} in m["steps"][1]["action"]


def test_u_times_state_is_the_exact_product():
    m = step_math(doc([nd("a", "shake", [0, 1])]))
    p = m["steps"][0]["product"]
    assert p["before"] == ["1", "0", "0", "0"] and p["after"] == ["1/2"] * 4 and p["basis"] == ["00", "01", "10", "11"]


def test_measure_branches_and_probabilities():
    m = step_math(doc([nd("a", "shake", [0]), nd("b", "measure", [0], classical=[0])], nc=1))
    s = m["steps"][1]
    assert s["measure"][0]["p0"] == pytest.approx(0.5) and len(s["after"]["branches"]) == 2
    assert sorted(b["bits"] for b in s["after"]["branches"]) == ["0", "1"]


def test_terms_match_the_real_statevector():
    d = doc([nd("a", "shake", [0, 1]), nd("b", "phase", [1], {"angle": {"pi": [1, 2]}})])
    m = step_math(d)
    t = m["steps"][1]["after"]["branches"][0]["terms"]
    assert sum(x["prob"] for x in t) == pytest.approx(1) and any("i" in x["amp"] for x in t)
    assert ket_string(terms_of(np.array([1, 0, 0, 0], dtype=complex), 2)[0]) == "|00⟩"


def test_too_many_qubits_is_said_not_faked():
    big = doc([nd("a", "shake", [0])], n=14)
    assert "too many" in step_math(big)["skipped"]


GOOD_TEXT = "Shake applies the H gate to each qubit, so |00⟩ becomes (|00⟩ + |01⟩ + |10⟩ + |11⟩)/2 and each qubit has a 50% chance of being 1."


class Resp:
    status_code = 200

    def __init__(self, text):
        self.text, self._t = "x", text

    def json(self):
        return {"choices": [{"message": {"content": json.dumps({"text": self._t})}}], "usage": {}}


class Sess:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def post(self, *a, **k):
        self.calls += 1
        return Resp(self.text)


def settings_with(**kw):
    base = dict(LLM_BASE_URL="https://llm.example/v1", LLM_API_KEY="sk-test", LLM_MODEL="m", LLM_FALLBACK_BASE_URL="",
                LLM_FALLBACK_API_KEY="", LLM_FALLBACK_MODEL="", LLM_TIMEOUT_S=5, LLM_DAILY_REQUEST_BUDGET=100, LOG_DIR="")
    base.update(kw)
    return SimpleNamespace(**base)


def go(text, **kw):
    d = doc([nd("N1", "shake", [0, 1])])
    log = analyze_document(d, code_check=False)
    sm = step_math(d)["steps"][0]
    s = Sess(text)
    return step_mod.explain_step(log, d, "N1", sm, None, ["Q1", "Q2"], settings_with(**kw), session=s), s


def test_checked_ai_text_is_returned_with_the_exact_maths():
    r, s = go(GOOD_TEXT)
    assert r["llm"]["status"] == "ok" and r["llm"]["text"] == GOOD_TEXT and r["template"]["text"] and r["math"]["matrix"]
    assert s.calls == 1


def test_ai_text_that_contradicts_the_maths_is_thrown_away():
    r, _ = go("Shake gives Q1 a 90% chance of being 1.")
    assert r["llm"]["status"] == "rejected" and r["llm"]["text"] is None and r["template"]["text"]


def test_decimal_amplitudes_are_not_accepted():
    r, _ = go("The amplitude of each qubit state is 0.7071, giving 50% for each qubit.")
    assert r["llm"]["status"] == "rejected"


def test_unconfigured_means_template_and_maths_only():
    r, s = go(GOOD_TEXT, LLM_BASE_URL="", LLM_API_KEY="", LLM_MODEL="")
    assert r["llm"]["status"] == "unconfigured" and s.calls == 0 and r["math"]["matrix"]


def test_same_step_is_asked_once():
    r, s = go(GOOD_TEXT)
    d = doc([nd("N1", "shake", [0, 1])])
    log = analyze_document(d, code_check=False)
    r2 = step_mod.explain_step(log, d, "N1", step_math(d)["steps"][0], None, ["Q1", "Q2"], settings_with(), session=s)
    assert s.calls == 1 and r2["llm"]["cache_hit"]


def test_endpoints():
    from fastapi.testclient import TestClient
    import app as backend_app
    c = TestClient(backend_app.app)
    d = doc([nd("N1", "shake", [0, 1])])
    r = c.post("/math", json={"document": d, "labels": ["Q1", "Q2"]})
    assert r.status_code == 200 and r.json()["steps"][0]["after"]["branches"][0]["ket"] == "(|00⟩ + |01⟩ + |10⟩ + |11⟩)/2"
    r = c.post("/explain-step", json={"document": d, "step_id": "N1", "labels": ["Q1", "Q2"], "use_llm": False})
    assert r.status_code == 200 and r.json()["template"]["text"] and r.json()["llm"]["status"] == "not_requested"
    assert c.post("/explain-step", json={"document": d, "step_id": "nope"}).status_code == 404
    assert c.post("/math", json={"document": {"nonsense": 1}}).status_code == 400
