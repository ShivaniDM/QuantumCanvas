from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    IONQ_API_KEY:  str = ""
    IONQ_ENDPOINT: str = "https://api.ionq.co"

    LOG_DIR: str = "../logs"

    CORS_ORIGINS: str = "*"

    ALLOW_QPU_SUBMIT: str = "off"

    MAX_QUBITS: int = 24
    MAX_SHOTS: int = 100_000

    RATE_LIMIT_PER_MINUTE: int = 30
    RATE_LIMIT_LIGHT_PER_MINUTE: int = 240

    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_FALLBACK_BASE_URL: str = ""
    LLM_FALLBACK_API_KEY: str = ""
    LLM_FALLBACK_MODEL: str = ""
    LLM_TIMEOUT_S: float = 25.0
    LLM_DAILY_REQUEST_BUDGET: int = 100

    ENGINE_URL: str = ""
    ENGINE_API_KEY: str = ""
    ENGINE_TIMEOUT_S: float = 180.0

    RESEARCH_LOGGING: str = "off"

    MONGODB_URI: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
