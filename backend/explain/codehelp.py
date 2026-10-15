from __future__ import annotations

import json

from . import llm
from .service import _parse_json

MAX_HELP_SOURCE_CHARS = 20_000

SYSTEM = """You help someone fix quantum circuit code so that QuantumCanvas can read it.
QuantumCanvas reads code without running it, and only accepts this subset:
- Qiskit: {qiskit}
- OpenQASM 2 or 3: gate statements on declared qubit registers, and measurements.
You get the code and the exact error message QuantumCanvas reported.
Rules:
1. Explain in two to four plain sentences what is wrong and what needs to change. Mention the line number when the error gives one.
2. Then give the full corrected code. Change only what is needed; keep everything else exactly as it was, including comment lines.
3. Use only constructs from the accepted subset.
Reply with JSON only, no markdown:
{{"explanation": "<plain sentences>", "fixed_source": "<the complete corrected code>"}}"""


def _check_fix(fmt: str, source: str, max_qubits: int) -> dict:
    from codeimport import ImportFailed, import_source
    from concepts import compile_document
    try:
        r = import_source(fmt, source, max_qubits)
    except ImportFailed as e:
        return {"ok": False, "message": str(e)}
    if not r.get("ok"):
        return {"ok": False, "message": r.get("error") or "It still can't be read."}
    c = compile_document(r["document"])
    if not c.ok:
        return {"ok": False, "message": " ".join(e.message for e in c.errors)}
    return {"ok": True, "message": f"{r['report']['qubits']} qubits, {r['report']['gates']} gates."}


def code_help(fmt: str, source: str, error: str, settings, session=None) -> dict:
    from codeimport.qiskit_subset import SUPPORTED_SUMMARY
    providers = llm.configured_providers(settings)
    if not providers:
        return {"status": "unconfigured", "message": "AI help is not set up on this server."}
    if len(source) > MAX_HELP_SOURCE_CHARS:
        return {"status": "too_long", "message": f"AI help works on code up to {MAX_HELP_SOURCE_CHARS:,} characters."}
    if not llm.budget_available(settings.LLM_DAILY_REQUEST_BUDGET):
        return {"status": "budget", "message": "Today's AI allowance on this server is used up. The error message above still applies."}
    messages = [{"role": "system", "content": SYSTEM.format(qiskit=SUPPORTED_SUMMARY)},
                {"role": "user", "content": json.dumps({"format": fmt, "error": error[:2000], "code": source}, ensure_ascii=False)}]
    for p in providers:
        try:
            llm.budget_spend()
            resp = llm.chat(p, messages, timeout=settings.LLM_TIMEOUT_S, max_tokens=1800, session=session)
        except (llm.QuotaExceeded, llm.ProviderError):
            continue
        parsed = _parse_json(resp["text"])
        if not isinstance(parsed, dict) or not isinstance(parsed.get("explanation"), str):
            return {"status": "unusable", "message": "The AI reply could not be used. The error message above still applies."}
        fixed = parsed.get("fixed_source") if isinstance(parsed.get("fixed_source"), str) else None
        out = {"status": "ok", "explanation": parsed["explanation"].strip(), "fixed_source": fixed,
               "provider": p.label, "model": p.model}
        if fixed:
            out["fix_check"] = _check_fix(fmt, fixed, settings.MAX_QUBITS)
        return out
    return {"status": "unavailable", "message": "The AI service isn't answering right now. The error message above still applies."}
