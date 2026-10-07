"""Secret redaction. Applied to every run record and every structured log line BEFORE anything is written.

Three layers: (1) values of secrets we know (env vars, passed in), (2) any key whose NAME looks secret,
(3) patterns that look like credentials in free text (Bearer tokens, sk-/gsk_ style keys, emails).
"""
from __future__ import annotations

import os
import re

REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"

_SECRET_KEY = re.compile(r"(api[_-]?key|token|secret|passw(or)?d|authorization|bearer|credential|mongodb_uri|private[_-]?key)", re.I)
# bounded quantifiers: a 200 KB run of letters must not cause catastrophic backtracking
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,24}")
_BEARER = re.compile(r"(Bearer|apiKey|Token)\s+[A-Za-z0-9._\-~+/=]{8,}", re.I)
_KEYLIKE = re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,}|gsk_[A-Za-z0-9]{12,}|cfut_[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{16})\b")
_URL_CRED = re.compile(r"(\w{1,20}://)([^/\s:@]{1,128}):([^/\s@]{1,256})@")

# environment variables whose VALUES must never appear in a record
SECRET_ENV_NAMES = ("LLM_API_KEY", "LLM_FALLBACK_API_KEY", "IONQ_API_KEY", "MONGODB_URI", "CF_API_TOKEN",
                    "GROQ_API_KEY", "AZUREAPPSERVICE_CLIENTID")


def known_secrets(extra=()) -> list[str]:
    vals = [os.environ.get(n, "") for n in SECRET_ENV_NAMES]
    try:                                                          # values the app was configured with via .env
        from config import settings
        for n in SECRET_ENV_NAMES:
            vals.append(str(getattr(settings, n, "") or ""))
    except Exception:
        pass
    vals += list(extra)
    return sorted({v for v in vals if v and len(v) >= 8 and not v.startswith("${{")}, key=len, reverse=True)


def redact_text(s: str, secrets=None) -> str:
    if not isinstance(s, str) or not s:
        return s
    for sec in (secrets if secrets is not None else known_secrets()):
        s = s.replace(sec, REDACTED)
    s = _URL_CRED.sub(lambda m: f"{m.group(1)}{REDACTED}:{REDACTED}@", s)
    s = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", s)
    s = _KEYLIKE.sub(REDACTED, s)
    return _EMAIL.sub(REDACTED_EMAIL, s)


def redact_json_text(s: str, secrets=None) -> str:
    """Redact a string that may be JSON: parse it so secret-looking KEYS are caught too, else treat it as text."""
    import json
    if isinstance(s, str) and s.lstrip()[:1] in ("{", "["):
        try:
            return json.dumps(redact(json.loads(s), secrets), indent=2, ensure_ascii=False)
        except Exception:
            pass
    return redact_text(s, secrets)


def redact(obj, secrets=None):
    """Return a deep copy with secrets removed. Dict keys that look secret lose their value entirely."""
    secrets = known_secrets() if secrets is None else secrets
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY.search(k) and not isinstance(v, (dict, list)):
                out[k] = REDACTED if v not in (None, "", False) else v
            else:
                out[k] = redact(v, secrets)
        return out
    if isinstance(obj, list):
        return [redact(v, secrets) for v in obj]
    if isinstance(obj, tuple):
        return [redact(v, secrets) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj, secrets)
    return obj
