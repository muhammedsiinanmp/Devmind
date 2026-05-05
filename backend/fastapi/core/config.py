from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")

    # Database
    fastapi_database_url: str = (
        "postgresql+asyncpg://devmind:devmind_secret@postgres:5432/devmind"
    )

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_max_tokens: int = 4096
    openai_temperature: float = 0.2

    # LLM Client (Google, Groq, GitHub)
    google_ai_api_key: str = ""
    groq_api_key: str = ""
    github_token: str = ""
    llm_failover_enabled: bool = True
    primary_llm_provider: str = "google"

    # Security
    fastapi_internal_secret: str = ""

    # Sentry
    sentry_dsn_fastapi: str = ""
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.1

    # Rate Limiting
    review_rate_limit_per_hour: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
