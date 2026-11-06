import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Generated or vendored files a review skips (REVIEW_SKIP_PATTERNS).
# Matched against the file's path and against its name, so "uv.lock" also
# matches "backend/uv.lock". "*" matches "/" too.
DEFAULT_SKIP_PATTERNS = [
    # Lockfiles
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
    # Minified bundles and source maps
    "*.min.js",
    "*.min.css",
    "*.map",
    # Test and migration snapshots
    "*.snap",
    "*/__snapshots__/*",
    "*_snapshot.json",
    # Generated protobuf code
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.pb.go",
    # Vendored dependencies
    "vendor/*",
    "*/vendor/*",
    "node_modules/*",
    "*/node_modules/*",
]

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

    # Large diffs are reviewed in batches of whole files that each fit one
    # prompt. At most REVIEW_MAX_BATCHES batches per review (files beyond it
    # are reported as skipped, "batch_limit"), and at most
    # REVIEW_MAX_CONCURRENT_BATCHES run at once; each batch makes one call
    # per analyzer, so this bounds concurrent provider requests to 3x it.
    review_max_batches: int = Field(default=6, ge=1)
    review_max_concurrent_batches: int = Field(default=2, ge=1)
    # Glob patterns of generated or vendored files that are not reviewed
    # (reported as skipped, "generated"). Set REVIEW_SKIP_PATTERNS to a JSON
    # list to replace DEFAULT_SKIP_PATTERNS above.
    review_skip_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SKIP_PATTERNS)
    )

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
