import os
from functools import lru_cache

from pydantic import Field
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

    # LLM Client (Google, then Groq). GitHub Models was retired on 2026-07-30
    # and was removed.
    google_ai_api_key: str = ""
    groq_api_key: str = ""
    llm_failover_enabled: bool = True
    primary_llm_provider: str = "google"

    # Server provider models. Pinned stable IDs rather than "-latest" aliases,
    # so a provider-side alias change can't silently change review output.
    google_model: str = "gemini-3.5-flash"
    groq_model: str = "openai/gpt-oss-120b"
    # Seconds /health caches each provider's model listing
    llm_health_cache_seconds: int = 300

    # Sampling temperature for review analyzer calls (REVIEW_TEMPERATURE).
    review_temperature: float = Field(default=0.1, ge=0.0, le=2.0)

    # Embeddings
    embedding_model: str = "text-embedding-004"

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
