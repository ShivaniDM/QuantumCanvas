import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

import app as backend_app
import executor
from config import settings
from explain import claims, llm
from explain.service import LABEL, explain, template_explanation
from mathlayer import analyze

FIX = Path(__file__).parent / "fixtures" / "runs"
RUN = json.loads((FIX / "f9e60a7115d2.json").read_text(encoding="utf-8"))
IR = json.loads(RUN["ir_json"])
COUNTS = RUN["results"]
LOG = analyze(RUN)
LABELS = ["Q1", "Q2"]

GOOD = {
    "summary": "The exact simulation predicts Q1 measures 1 about 10% of the time, and your counts agree.",
    "steps": [
        {"id": "N1", "text": "Encode tilts Q2 so its chance of 1 becomes 20%, but Q2 is never measured, so this step doesn't change your result."},
        {"id": "N2", "text": "Encode tilts Q1 so its chance of 1 goes from 0% to 80%."},
        {"id": "N3", "text": "Shake does not give a 50/50 split here: Q1 goes from 80% to 10% and Q2 from 20% to 10%, so the encoded data is overwritten."},
        {"id": "N4", "text": "Entangle links Q1 and Q2 (entanglement of Q1 with the rest goes from 0.00 to 0.33 bits), but it does not change what you measure."},
        {"id": "N5", "text": "Mark only flips a hidden sign, so no probability changes and it doesn't affect your measurement."},
        {"id": "N6", "text": "Boost lowered the chance of the marked answer from 82% to 18%: with one qubit it just flips the qubit instead of amplifying, and it doesn't change your result."},
        {"id": "N8", "text": "Q1 is measured and the answer is stored in a classical bit."},
    ],
}


def settings_with(**kw):
    base = dict(LLM_BASE_URL="https://llm.example/v1", LLM_API_KEY="sk-test-KEY-1234567890abcdef", LLM_MODEL="m1",
                LLM_FALLBACK_BASE_URL="", LLM_FALLBACK_API_KEY="", LLM_FALLBACK_MODEL="", LLM_TIMEOUT_S=5,
                LLM_DAILY_REQUEST_BUDGET=100, LOG_DIR="")
    base.update(kw)
    return SimpleNamespace(**base)


class FakeResp:
    def __init__(self, status=200, content=None, text=None):
        self.status_code, self._content, self.text = status, content, text or (json.dumps({"choices": [{"message": {"content": content}}]}) if content else "")

    def json(self):
        return {"choices": [{"message": {"content": self._content}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "body": json})
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    from explain import service
    service._mem_cache.clear()
    llm.budget_reset()
    monkeypatch.setattr(settings, "LOG_DIR", str(tmp_path), raising=False)
    return tmp_path


def run_explain(session, use_llm=True, **kw):
    return explain(LOG, IR, COUNTS, LABELS, settings_with(LOG_DIR=str(settings.LOG_DIR), **kw), use_llm=use_llm, session=session)


def test_template_is_rendered_from_the_step_log_and_is_honest():
    t = template_explanation(LOG, IR, COUNTS, LABELS)
    by = {s["id"]: s for s in t["steps"]}
    assert "LOWERED" in by["N6"]["text"] and "82% → 18%" in by["N6"]["text"] and by["N6"]["claim_ok"] is False
    assert "already a mix" in by["N3"]["text"] and "80% → 10%" in by["N3"]["text"]
    assert "Removing this step wouldn't change your result." in by["N4"]["text"]
    assert "Removing this step" not in by["N2"]["text"]
    assert "|0⟩ 90%" in t["summary"] and "agree" in t["summary"] and "4 of 7 steps" in t["summary"]


def test_template_works_for_circuits_without_a_measurement():
    from mathlayer import analyze_document
    doc = {"version": "0.3", "qubits": 2, "classical_bits": 0, "operations": [
        {"id": "a", "op": "shake", "targets": [0]}, {"id": "b", "op": "entangle", "targets": [0, 1]}]}
    t = template_explanation(analyze_document(doc, code_check=False), doc, None, ["Q1", "Q2"])
    assert "no Measure step" in t["summary"] and "q0 → c0, q1 → c1" in t["summary"] and len(t["steps"]) == 2
    assert "|00⟩ 50%" in t["summary"] and "|11⟩ 50%" in t["summary"]


def test_superposition_on_one_is_not_flagged():
    from mathlayer import analyze_document
    doc = {"version": "0.4", "qubits": 1, "classical_bits": 0, "operations": [
        {"id": "a", "op": "flip", "targets": [0]}, {"id": "b", "op": "shake", "targets": [0]}]}
    t = template_explanation(analyze_document(doc, code_check=False, results={"0": 500, "1": 500}), doc, {"0": 500, "1": 500}, ["q0"])
    b = {s["id"]: s for s in t["steps"]}["b"]
    assert b["claim_ok"] is not False and "still 50/50" in b["text"] and "agree" in t["summary"]


def chk(parsed):
    return claims.check_llm_output(parsed, LOG, IR, COUNTS)


def test_truthful_text_passes():
    assert chk(GOOD)["passed"], chk(GOOD)["violations"]


def test_deliberately_wrong_response_is_rejected():
    bad = copy.deepcopy(GOOD)
    bad["steps"][5]["text"] = "Boost makes the marked answer more likely, raising it from 18% to 82%."
    r = chk(bad)
    assert not r["passed"] and any(v["where"] == "N6" and v["type"] == "direction" for v in r["violations"])


@pytest.mark.parametrize("sid,idx,text,vtype", [
    ("N3", 2, "Shake puts both qubits into an even 50/50 mix.", "direction"),
    ("N3", 2, "Shake sets Q1 to 63% and Q2 to 10%.", "number"),
    ("N2", 1, "Encode sets Q1's chance of 1 to 0.37.", "number"),
    ("N4", 3, "Entangle links Q1 and Q2 and changes what you measure.", None),
    ("N6", 5, "Boost worked perfectly as expected.", "omission"),
    ("N1", 0, "Encode tilts Q2 to a 20% chance of 1.", "omission"),
    ("N5", 4, "Mark changes the probabilities a lot, raising Q2 to 70%.", "number"),
])
def test_each_kind_of_false_claim_is_caught(sid, idx, text, vtype):
    bad = copy.deepcopy(GOOD)
    bad["steps"][idx]["text"] = text
    r = chk(bad)
    if vtype is None:
        assert r["passed"] or all(v["type"] != "number" for v in r["violations"])
        return
    assert not r["passed"] and any(v["where"] == sid and v["type"] == vtype for v in r["violations"]), r["violations"]


def test_numbers_in_the_summary_must_come_from_the_log():
    bad = copy.deepcopy(GOOD)
    bad["summary"] = "Q1 measures 1 about 42% of the time."
    assert any(v["where"] == "summary" and v["type"] == "number" for v in chk(bad)["violations"])


def test_unknown_step_ids_and_wrong_shapes_are_rejected():
    bad = copy.deepcopy(GOOD); bad["steps"].append({"id": "N99", "text": "x"})
    assert any(v["type"] == "unknown_step" for v in chk(bad)["violations"])
    assert not chk({"summary": 1, "steps": "no"})["passed"]


def test_a_broken_step_may_not_be_silently_skipped():
    bad = copy.deepcopy(GOOD); bad["steps"] = [s for s in bad["steps"] if s["id"] != "N6"]
    assert any(v["where"] == "N6" and v["type"] == "omission" for v in chk(bad)["violations"])


def test_negation_is_understood():
    ok = copy.deepcopy(GOOD)
    ok["steps"][5]["text"] = "Boost does not make the marked answer more likely: it lowered it from 82% to 18% (one qubit only flips), so it doesn't change your result."
    assert chk(ok)["passed"], chk(ok)["violations"]


def good_session(*extra):
    return FakeSession(FakeResp(200, json.dumps(GOOD)), *extra)


def test_grounded_llm_text_is_returned_labelled_and_checked():
    s = good_session()
    r = run_explain(s)
    assert r["llm"]["status"] == "ok" and r["llm"]["label"] == LABEL and r["llm"]["text"]["steps"][5]["id"] == "N6"
    assert r["llm"]["claim_check"]["passed"] and r["llm"]["provider"] == "primary" and r["llm"]["tokens"]["total"] == 150
    call = s.calls[0]
    assert call["url"] == "https://llm.example/v1/chat/completions" and call["headers"]["Authorization"].startswith("Bearer ")
    assert call["body"]["model"] == "m1" and call["body"]["temperature"] == 0
    content = call["body"]["messages"][1]["content"]
    assert content.startswith("STEP LOG:")

    def keys(o):
        if isinstance(o, dict):
            return set(o) | set().union(*(keys(v) for v in o.values()))
        if isinstance(o, list):
            return set().union(*(keys(v) for v in o)) if o else set()
        return set()
    assert not [k for k in keys(json.loads(content[len("STEP LOG:"):])) if "amplitude" in k.lower() or "statevector" in k.lower()]
    assert len(r["template"]["steps"]) == 7


def test_contradicting_llm_text_is_never_returned_and_the_template_stands():
    bad = copy.deepcopy(GOOD); bad["steps"][5]["text"] = "Boost makes the marked answer more likely."
    r = run_explain(FakeSession(FakeResp(200, json.dumps(bad))))
    assert r["llm"]["status"] == "rejected" and r["llm"]["text"] is None
    assert r["llm"]["claim_check"]["violations"] and r["llm"]["response"]
    assert "LOWERED" in {s["id"]: s for s in r["template"]["steps"]}["N6"]["text"]


def test_non_json_reply_is_rejected():
    r = run_explain(FakeSession(FakeResp(200, "Sure! Here is an explanation: it all worked great.")))
    assert r["llm"]["status"] == "rejected" and r["llm"]["claim_check"]["violations"][0]["type"] == "format"


def test_json_inside_a_markdown_fence_is_accepted():
    r = run_explain(FakeSession(FakeResp(200, "```json\n" + json.dumps(GOOD) + "\n```")))
    assert r["llm"]["status"] == "ok"


def test_cache_means_one_provider_call_for_the_same_circuit():
    s = good_session()
    run_explain(s)
    b = run_explain(s)
    assert len(s.calls) == 1 and b["llm"]["cache_hit"] is True and b["llm"]["status"] == "ok"
    s2 = good_session()
    from explain import service
    service._mem_cache.clear()
    assert run_explain(s2)["llm"]["cache_hit"] is True and not s2.calls


def test_rejected_text_is_not_cached():
    bad = copy.deepcopy(GOOD); bad["summary"] = "Q1 measures 1 about 42% of the time."
    s = FakeSession(FakeResp(200, json.dumps(bad)), FakeResp(200, json.dumps(GOOD)))
    assert run_explain(s)["llm"]["status"] == "rejected"
    assert run_explain(s)["llm"]["status"] == "ok" and len(s.calls) == 2


def test_quota_on_the_primary_falls_back_to_the_secondary():
    s = FakeSession(FakeResp(429, text="rate limited"), FakeResp(200, json.dumps(GOOD)))
    r = run_explain(s, LLM_FALLBACK_BASE_URL="https://groq.example/openai/v1", LLM_FALLBACK_API_KEY="gsk_fallbackkey123456", LLM_FALLBACK_MODEL="m2")
    assert r["llm"]["status"] == "ok" and r["llm"]["fallback_used"] is True and r["llm"]["provider"] == "fallback"
    assert [c["url"] for c in s.calls] == ["https://llm.example/v1/chat/completions", "https://groq.example/openai/v1/chat/completions"]
    assert r["llm"]["attempts"][0]["kind"] == "quota"


def test_quota_everywhere_falls_back_to_template_only_without_raising():
    s = FakeSession(FakeResp(429, text="Daily free allocation of 10,000 neurons exceeded"))
    r = run_explain(s)
    assert r["llm"]["status"] == "unavailable" and r["llm"]["text"] is None and r["template"]["steps"]


def test_provider_outage_and_timeout_do_not_break_the_page():
    import requests
    r = run_explain(FakeSession(requests.ConnectionError("boom: sk-test-KEY-1234567890abcdef")))
    assert r["llm"]["status"] == "unavailable"
    assert "sk-test-KEY" not in json.dumps(r["llm"]["attempts"])
    assert run_explain(FakeSession(FakeResp(500, text="oops")))["llm"]["status"] == "unavailable"


def test_unset_key_or_url_means_template_only():
    s = FakeSession(FakeResp(200, json.dumps(GOOD)))
    for kw in ({"LLM_API_KEY": ""}, {"LLM_BASE_URL": ""}, {"LLM_MODEL": ""}):
        r = run_explain(s, **kw)
        assert r["llm"]["status"] == "unconfigured" and r["template"]["steps"]
    assert not s.calls


def test_daily_budget_protects_a_free_allowance():
    s = good_session()
    r1 = run_explain(s, LLM_DAILY_REQUEST_BUDGET=1)
    from explain import service
    service._mem_cache.clear(); 
    for f in (Path(settings.LOG_DIR) / "explain_cache").glob("*.json"):
        f.unlink()
    r2 = run_explain(s, LLM_DAILY_REQUEST_BUDGET=1)
    assert r1["llm"]["status"] == "ok" and r2["llm"]["status"] == "budget" and len(s.calls) == 1


def test_use_llm_false_never_calls_the_provider():
    s = good_session()
    assert run_explain(s, use_llm=False)["llm"]["status"] == "not_requested" and not s.calls


client = TestClient(backend_app.app)


def store_reviewed_run():
    from runlog import RunRecorder
    rec = RunRecorder(backend_requested="aer", shots=1000)
    rec.identity.update(circuit_hash="c" * 64, circuit_folder="cccccccccccc")
    rec.input.update(ir_json=IR, canvas_json=None)
    rec.compile.update(qiskit_py=RUN["qiskit_py"])
    rec.execution.update(backend_executed="aer_simulator", seed=1)
    rec.results.update(counts=COUNTS, math_log=LOG)
    rec.finish()
    executor.store().save(rec.to_record())
    return rec.run_id


def test_explain_endpoint_template_only_when_no_key(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.setattr(settings, k, "", raising=False)
    rid = store_reviewed_run()
    r = client.post("/explain", json={"record_id": rid, "labels": LABELS}).json()
    assert r["llm"]["status"] == "unconfigured" and len(r["template"]["steps"]) == 7
    rec = executor.store().load(rid)
    assert rec["revision"] == 2 and rec["explanation"]["llm"]["status"] == "unconfigured"


def test_explain_endpoint_with_a_mocked_provider_rejects_and_logs_the_failure(monkeypatch):
    import requests
    bad = copy.deepcopy(GOOD); bad["steps"][5]["text"] = "Boost makes the marked answer more likely."
    fake = FakeSession(FakeResp(200, json.dumps(bad)))
    monkeypatch.setattr(requests, "post", fake.post)
    for k, v in (("LLM_BASE_URL", "https://llm.example/v1"), ("LLM_API_KEY", "sk-test-KEY-1234567890abcdef"), ("LLM_MODEL", "m1")):
        monkeypatch.setattr(settings, k, v, raising=False)
    rid = store_reviewed_run()
    r = client.post("/explain", json={"record_id": rid, "labels": LABELS}).json()
    assert r["llm"]["status"] == "rejected" and r["llm"]["text"] is None
    assert "prompt" not in r["llm"] and "response" not in r["llm"]
    rec = executor.store().load(rid)
    assert rec["explanation"]["llm"]["prompt"] and rec["explanation"]["llm"]["response"]
    assert any(f["flag"] == "llm_claim_check_failed" for f in rec["flags"])
    assert "sk-test-KEY" not in json.dumps(rec) and "sk-test-KEY" not in json.dumps(r)


def test_explain_endpoint_errors_and_health():
    assert client.post("/explain", json={"record_id": "nope"}).status_code == 404
    assert client.post("/explain", json={}).status_code == 400
    h = client.get("/health").json()
    assert isinstance(h["llm_configured"], int) and "key" not in json.dumps(h).lower().replace("ionq_configured", "")


def test_explain_a_document_that_was_not_run_yet(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.setattr(settings, k, "", raising=False)
    doc = {"version": "0.3", "qubits": 2, "classical_bits": 2, "operations": [
        {"id": "a", "op": "shake", "targets": [0]}, {"id": "b", "op": "entangle", "targets": [0, 1]},
        {"id": "c", "op": "measure", "targets": [0, 1], "classical": [0, 1]}]}
    r = client.post("/explain", json={"document": doc, "labels": ["Q1", "Q2"]}).json()
    assert [s["claim_ok"] for s in r["template"]["steps"]][:2] == [True, True] and "|00⟩ 50%" in r["template"]["summary"]


def test_entropy_bits_are_not_mistaken_for_percentages():
    from mathlayer import analyze_document
    bell = {"version": "0.3", "qubits": 2, "classical_bits": 2, "operations": [
        {"id": "N1", "op": "shake", "targets": [0]}, {"id": "N2", "op": "entangle", "targets": [0, 1]},
        {"id": "N3", "op": "measure", "targets": [0, 1], "classical": [0, 1]}]}
    log = analyze_document(bell, code_check=False)
    parsed = {"summary": "Q1 and Q2 give 00 or 11, each about 50% of the time.",
              "steps": [{"id": "N1", "text": "Shake puts Q1 into an even 50/50 mix."},
                        {"id": "N2", "text": "Entangle links Q1 and Q2, so their answers always agree."},
                        {"id": "N3", "text": "Q1 and Q2 are measured."}]}
    assert claims.check_llm_output(parsed, log, bell, None)["passed"]
    for bad_text in ("Entangle makes Q1 and Q2 more likely, up to 99%.", "Entangle raises the chance of 1 to 70%.",
                     "Entanglement of Q1 reaches 0.70 bits."):
        parsed["steps"][1]["text"] = bad_text
        r = claims.check_llm_output(parsed, log, bell, None)
        assert not r["passed"] and any(v["type"] == "number" for v in r["violations"]), (bad_text, r["violations"])
    parsed["steps"][1]["text"] = "Entanglement of Q1 with the rest reaches 1.00 bits."
    assert claims.check_llm_output(parsed, log, bell, None)["passed"]


def test_percentages_must_match_to_the_rounding_a_person_would_use():
    ok = copy.deepcopy(GOOD); ok["steps"][5]["text"] = ok["steps"][5]["text"].replace("82%", "82.4%")
    assert chk(ok)["passed"]
    bad = copy.deepcopy(GOOD); bad["steps"][5]["text"] = bad["steps"][5]["text"].replace("82%", "84%")
    assert any(v["type"] == "number" for v in chk(bad)["violations"])


def test_template_steps_have_titles_with_canvas_names_and_a_plain_sentence():
    by = {s["id"]: s for s in template_explanation(LOG, IR, COUNTS, LABELS)["steps"]}
    assert by["N3"]["title"] == "SUPERPOSE [Q1, Q2]" and "q0" not in by["N4"]["title"]
    assert by["N2"]["text"].startswith("Encode turns each number into a tilt")
    assert "already a mix" in by["N3"]["text"] and "Encode turns" not in by["N3"]["text"]


def test_check_llm_tool_never_prints_the_key(monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_llm", Path(__file__).parent.parent / "tools" / "check_llm.py")
    tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
    for k, v in (("LLM_BASE_URL", "https://llm.example/v1"), ("LLM_API_KEY", "sk-test-KEY-1234567890abcdef"), ("LLM_MODEL", "m1")):
        monkeypatch.setattr(settings, k, v, raising=False)
    import requests
    monkeypatch.setattr(requests, "post", FakeSession(FakeResp(200, "Superposition means both at once.")).post)
    assert tool.main() == 0
    out = capsys.readouterr().out
    assert "sk-test-KEY" not in out and "Superposition means both" in out and "not shown" in out


def test_every_template_step_carries_principle_math_and_code():
    t = template_explanation(LOG, IR, COUNTS, LABELS)
    for s in t["steps"]:
        assert s["principle"]["name"] and s["principle"]["idea"]
        assert s["math"]
    shake = next(s for s in t["steps"] if s["concept"] == "shake")
    assert shake["principle"]["name"] == "Superposition" and "qc.h(" in shake["code"]


def test_the_prompt_hands_the_model_each_steps_principle():
    from explain.prompt import SYSTEM, build_messages
    payload = json.loads(build_messages(LOG, IR, COUNTS, LABELS)[1]["content"][len("STEP LOG:"):])
    assert all(s["principle"]["name"] for s in payload["steps"])
    assert "principle" in SYSTEM


def test_principles_that_match_the_step_pass():
    ok = copy.deepcopy(GOOD)
    for s in ok["steps"]:
        s["principle"] = {"N1": "State preparation sets Q2's chance.", "N2": "State preparation sets Q1's chance.",
                          "N3": "Superposition needs a qubit that starts at 0.",
                          "N4": "Entanglement links the two qubits.", "N5": "Phase oracle: only a sign changes.",
                          "N6": "Amplitude amplification relies on interference, which needs more than one qubit.",
                          "N8": "Measurement follows the Born rule."}[s["id"]]
    assert chk(ok)["passed"], chk(ok)["violations"]


def test_a_principle_that_names_the_wrong_idea_is_rejected():
    bad = copy.deepcopy(GOOD)
    bad["steps"][2]["principle"] = "Entanglement makes the two qubits act as one."
    r = chk(bad)
    assert not r["passed"] and any(v["type"] == "principle" for v in r["violations"])


def test_numbers_in_a_principle_must_come_from_the_log():
    bad = copy.deepcopy(GOOD)
    bad["steps"][1]["principle"] = "State preparation gives a 73% chance here."
    assert not chk(bad)["passed"]


BROKEN = "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.x(0)fsaoi\n"
FIXED = "from qiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.x(0)\n"


def test_code_help_checks_the_suggested_fix_by_importing_it():
    from explain.codehelp import code_help
    llm.budget_reset()
    reply = json.dumps({"explanation": "Line 4 has extra text after qc.x(0).", "fixed_source": FIXED})
    s = settings_with(LLM_BASE_URL="https://llm.example/v1", LLM_API_KEY="k", LLM_MODEL="m", MAX_QUBITS=24)
    out = code_help("qiskit", BROKEN, "Line 4: not valid Python: invalid syntax", s, session=FakeSession(FakeResp(200, reply)))
    assert out["status"] == "ok" and out["fix_check"]["ok"] is True and "Line 4" in out["explanation"]


def test_code_help_reports_a_fix_that_still_fails():
    from explain.codehelp import code_help
    llm.budget_reset()
    reply = json.dumps({"explanation": "Try this.", "fixed_source": BROKEN})
    s = settings_with(LLM_BASE_URL="https://llm.example/v1", LLM_API_KEY="k", LLM_MODEL="m", MAX_QUBITS=24)
    out = code_help("qiskit", BROKEN, "Line 4: not valid Python", s, session=FakeSession(FakeResp(200, reply)))
    assert out["status"] == "ok" and out["fix_check"]["ok"] is False


def test_code_help_without_an_llm_says_so():
    from explain.codehelp import code_help
    out = code_help("qiskit", BROKEN, "x", settings_with(LLM_BASE_URL="", LLM_API_KEY="", LLM_MODEL="", MAX_QUBITS=24))
    assert out["status"] == "unconfigured"
