import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Path of the dotenv file to read. Set DEVMIND_ENV_FILE="" to disable it
# (the test suite does this so it never picks up real keys or Sentry DSNs).
ENV_FILE = os.environ.get("DEVMIND_ENV_FILE", "../../.env") or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # Database
    fastapi_database_url: str = (
        "postgresql+asyncpg://devmind:devmind_secret@postgres:5432/devmind"
    )

    # LLM Client (Google, Groq, GitHub)
    google_ai_api_key: str = ""
    groq_api_key: str = ""
    github_token: str = ""
    llm_failover_enabled: bool = True
    primary_llm_provider: str = "google"

    # Embeddings
    embedding_model: str = "gemini-embedding-001"

    # Security
    fastapi_internal_secret: str = ""
    django_base_url: str = "http://django:8000"

    # Sentry
    sentry_dsn_fastapi: str = ""
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.1

    # Rate Limiting
    review_rate_limit_per_hour: int = 20
    redis_url: str = "redis://redis:6379/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
