"""
QuantumCanvas — Configuration
Reads from .env via python-dotenv.
Keys are NEVER passed to the frontend.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # IonQ credentials — loaded from .env, never committed to git
    IONQ_API_KEY:  str = "${{ IONQ_API_KEY }}"
    IONQ_ENDPOINT: str = "https://api.ionq.co"

    # Logging
    LOG_DIR: str = "../logs"

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
