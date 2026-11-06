import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _empty_as_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


# A server provider's temperature setting: a number, "omit" (send none), or
# None (use the caller's temperature). An empty variable counts as None.
ProviderTemperature = Annotated[
    Annotated[float, Field(ge=0.0, le=2.0)] | Literal["omit"] | None,
    BeforeValidator(_empty_as_none),
]

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
    # gemini-3.5-flash is deprecated (Google routes it to gemini-3.6-flash);
    # gemini-3.6-flash answered a JSON-mode request with no temperature on
    # 2026-11-06. gemini-3.8-flash returned 503 "high demand" that day.
    google_model: str = "gemini-3.6-flash"
    groq_model: str = "openai/gpt-oss-120b"
    # Seconds /health caches each provider's model listing
    llm_health_cache_seconds: int = 300

    # Sampling temperature for review analyzer calls (REVIEW_TEMPERATURE).
    review_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    # Per-provider overrides for the server providers (GOOGLE_TEMPERATURE,
    # GROQ_TEMPERATURE): a number from 0 to 2 replaces the caller's
    # temperature, "omit" sends no temperature (the provider's default
    # applies), and unset or empty uses the caller's (REVIEW_TEMPERATURE for
    # reviews). Google's docs for all Gemini 3.x models recommend not changing
    # the sampling defaults and removing temperature from requests, so Google
    # omits it by default.
    google_temperature: ProviderTemperature = "omit"
    groq_temperature: ProviderTemperature = None

    # Large diffs are reviewed in batches of whole files that each fit one
    # prompt. At most REVIEW_MAX_BATCHES batches per review (files beyond it
    # are reported as skipped, "batch_limit"), and at most
    # REVIEW_MAX_CONCURRENT_BATCHES run at once; each batch makes one call
    # per analyzer, so this bounds concurrent provider requests to 3x it.
    review_max_batches: int = Field(default=6, ge=1)
    review_max_concurrent_batches: int = Field(default=2, ge=1)
    # Seconds a review may spend from the start of POST /review/analyze to the
    # end of its batches (REVIEW_DEADLINE_SECONDS). Batches still running then
    # are cancelled and their files reported as skipped ("deadline"). It must
    # be below Django's FASTAPI_TIMEOUT_SECONDS (default 120), or Django gives
    # up before the partial review is returned. 100 s fits 6 batches (18
    # calls, 3 rounds of 2 batches) including one wait for Google's 15
    # requests-per-minute window (up to 60 s), and leaves 20 s of Django's
    # timeout for anchoring, the response and network.
    review_deadline_seconds: float = Field(default=100, gt=0)
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
