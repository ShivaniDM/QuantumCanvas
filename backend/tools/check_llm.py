import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from explain import llm


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
