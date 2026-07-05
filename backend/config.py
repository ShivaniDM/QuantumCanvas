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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
