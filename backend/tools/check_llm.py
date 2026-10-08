"""Check the LLM_* settings with ONE real call, without ever printing the key.

    cd backend && python tools/check_llm.py            # reads backend/.env or the environment (Azure app settings)

Prints: which providers are configured (names only), the HTTP outcome, latency, token usage and the reply.
Exit code 0 = the primary provider answered. Safe to run on Azure (SSH / Kudu console).
"""
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):                 # Windows consoles default to cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings                         # noqa: E402
from explain import llm                              # noqa: E402


def main() -> int:
    providers = llm.configured_providers(settings)
    if not providers:
        print("No provider configured. Set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL (see .env.example).")
        return 2
    code = 1
    for p in providers:
        print(f"[{p.label}] base_url={p.base_url}  model={p.model}  key=<set, {len(p.api_key)} chars, not shown>")
        try:
            r = llm.chat(p, [{"role": "user", "content": "Explain superposition in one sentence."}], timeout=settings.LLM_TIMEOUT_S, max_tokens=80)
            print(f"  OK  {r['latency_ms']} ms  tokens={r['tokens']}\n  reply: {r['text'].strip()[:300]}")
            code = 0 if p.label == "primary" else code
        except llm.QuotaExceeded as e:
            print(f"  QUOTA  {e}  (the fallback chain would take over)")
        except llm.ProviderError as e:
            print(f"  FAILED {e}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
