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
