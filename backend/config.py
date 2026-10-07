"""
QuantumCanvas — Configuration
Reads from .env via python-dotenv.
Keys are NEVER passed to the frontend.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # IonQ credentials — loaded from .env, never committed to git
    IONQ_API_KEY:  str = ""
    IONQ_ENDPOINT: str = "https://api.ionq.co"

    # Logging
    LOG_DIR: str = "../logs"

    # ── Security knobs (2026 security review) ──────────────────────────────
    # Comma-separated list of frontend origins allowed to call this API. "*" (the old
    # default) lets ANY website drive a visitor's browser into this API, including the
    # paid IonQ/QPU routes below — set this to your real frontend origin(s) in production.
    CORS_ORIGINS: str = "*"

    # Real quantum hardware costs real money per job. Submitting to it is OFF by default;
    # the frontend's "confirm the cost" dialog is a UI nicety, not a security boundary, so
    # this is the actual gate. Set to "on" only once you also have auth/quota in front of it.
    ALLOW_QPU_SUBMIT: str = "off"

    # Hard ceiling on circuit size / shots for /execute and /compile. Aer needs 2**qubits
    # amplitudes in memory — uncapped, one request can exhaust the server for everyone.
    MAX_QUBITS: int = 24
    MAX_SHOTS: int = 100_000

    # Simple in-memory per-IP rate limit for the expensive routes (/execute, /cost, /compile).
    # Not shared across multiple server instances — fine for a single App Service instance;
    # swap for a Redis-backed limiter if you scale out.
    RATE_LIMIT_PER_MINUTE: int = 30

    # Explanation layer (plan 9b). Provider-neutral and OpenAI-compatible: switching provider = changing these values,
    # not code. Unset => the explanation layer runs template-only. Keys live server-side ONLY.
    #   Cloudflare Workers AI: LLM_BASE_URL=https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1
    #                          LLM_MODEL=@cf/meta/llama-3.1-8b-instruct
    #   Groq:                  LLM_BASE_URL=https://api.groq.com/openai/v1
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_FALLBACK_BASE_URL: str = ""
    LLM_FALLBACK_API_KEY: str = ""
    LLM_FALLBACK_MODEL: str = ""
    LLM_TIMEOUT_S: float = 25.0
    LLM_DAILY_REQUEST_BUDGET: int = 100      # stay inside a free daily allowance; 0 = no limit. Resets 00:00 UTC.

    # Research interaction logging (Paper A). OFF unless explicitly turned on AND each event carries consent.
    RESEARCH_LOGGING: str = "off"

    # Optional MongoDB Atlas mirror — if set, every circuit save/execution is
    # also written to Mongo so runs persist even when this backend's local
    # disk is ephemeral (e.g. hosted on Azure). Blank = mirror silently skipped.
    MONGODB_URI: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"   # tolerate unrelated .env entries (e.g. Atlas's sample vars)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
