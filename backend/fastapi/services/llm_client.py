"""
LLM Client with automatic failover chain.

Supports multiple LLM providers:
1. Google Gemini (primary)
2. Groq (fallback)

GitHub Models was retired on 2026-07-30 and was removed.
Model IDs come from settings (core/config.py).
Automatically fails over on rate limits, unknown models, service errors or
timeouts.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from core.config import get_settings
from services.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    GOOGLE = "google"
    GROQ = "groq"
    OPENAI = "openai"
    CUSTOM = "custom"
    MISTRAL = "mistral"
    GOOGLE_VERTEX = "google_vertex"


class RateLimitError(Exception):
    """Raised when provider rate limit is exceeded."""

    pass


class ServiceUnavailableError(Exception):
    """Raised when provider service is unavailable."""

    pass


class ModelNotFoundError(ServiceUnavailableError):
    """Raised on a 404: the provider doesn't serve the configured model."""

    pass


class JSONModeRejectedError(ServiceUnavailableError):
    """Raised on a 4xx to a request with response_format (not 401/403/404/429)."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class TimeoutError(Exception):
    """Raised when provider request times out."""

    pass


class AllProvidersDownError(Exception):
    """Raised when all LLM providers are unavailable."""

    pass


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for an LLM provider."""

    provider: LLMProvider
    model: str
    api_key: str
    base_url: str
    max_tokens: int
    rpm_limit: int


@dataclass
class LLMResponse:
    """Response from LLM call."""

    content: str
    model_used: str
    provider: LLMProvider
    prompt_tokens: int
    completion_tokens: int


MODEL_CHAIN: list[LLMConfig] = []

GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _parse_provider(provider: str) -> LLMProvider | None:
    mapping = {
        "google": LLMProvider.GOOGLE,
        "groq": LLMProvider.GROQ,
        "openai": LLMProvider.OPENAI,
        "custom": LLMProvider.CUSTOM,
        "mistral": LLMProvider.MISTRAL,
        "google_vertex": LLMProvider.GOOGLE_VERTEX,
    }
    return mapping.get(provider.strip().lower())


def _init_model_chain() -> list[LLMConfig]:
    """Initialize the model chain with configurations."""
    chain = []

    if settings.google_ai_api_key:
        chain.append(
            LLMConfig(
                provider=LLMProvider.GOOGLE,
                model=settings.google_model,
                api_key=settings.google_ai_api_key,
                base_url=GOOGLE_BASE_URL,
                max_tokens=8192,
                rpm_limit=15,
            )
        )

    if settings.groq_api_key:
        chain.append(
            LLMConfig(
                provider=LLMProvider.GROQ,
                model=settings.groq_model,
                api_key=settings.groq_api_key,
                base_url=GROQ_BASE_URL,
                max_tokens=4096,
                rpm_limit=30,
            )
        )

    return chain


# Providers whose OpenAI-compatible endpoint accepts
# response_format={"type": "json_object"}. A custom endpoint may not, so it
# gets no response_format and the caller's tolerant parser handles its reply.
JSON_MODE_PROVIDERS = frozenset(
    {
        LLMProvider.GOOGLE,
        LLMProvider.GOOGLE_VERTEX,
        LLMProvider.GROQ,
        LLMProvider.OPENAI,
        LLMProvider.MISTRAL,
    }
)


def _request_body(
    config: LLMConfig, messages: list[dict[str, str]], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """
    Chat completions request body.

    ``temperature`` and ``max_tokens`` come from kwargs when given.
    ``json_mode=True`` asks for a JSON object reply where the provider
    supports it.
    """
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "max_tokens": kwargs.get("max_tokens", config.max_tokens),
        "temperature": kwargs.get("temperature", 0.7),
    }
    if kwargs.get("json_mode") and config.provider in JSON_MODE_PROVIDERS:
        body["response_format"] = {"type": "json_object"}
    return body


def _raise_if_json_mode_rejected(
    config: LLMConfig, body: dict[str, Any], status: int
) -> None:
    """
    A 4xx to a JSON-mode request may mean the provider rejected
    response_format, e.g. Groq's 400 json_validate_failed. Auth errors, a
    missing model and rate limits are not about JSON mode.
    """
    if "response_format" in body and 400 <= status < 500:
        if status not in (401, 403, 404, 429):
            raise JSONModeRejectedError(
                f"JSON mode rejected: {config.provider.value} {status}", status
            )


class LLMClient:
    """
    Multi-provider LLM client with automatic failover.

    Tries providers in order until one succeeds.
    Falls back to next provider on RateLimitError, ServiceUnavailableError, or TimeoutError.
    """

    def __init__(self):
        global MODEL_CHAIN
        MODEL_CHAIN = _init_model_chain()

        for config in MODEL_CHAIN:
            rate_limiter.add_provider(config.provider.value, config.rpm_limit)

    async def get_user_llm_configs(self, user_id: int) -> list[LLMConfig]:
        """
        Fetch active user BYOK configs from Django.

        FastAPI fetches decrypted keys through an internal authenticated endpoint.
        """
        if not user_id:
            return []

        base_url = getattr(settings, "django_base_url", "").rstrip("/")
        internal_secret = settings.fastapi_internal_secret
        if not base_url or not internal_secret:
            return []

        endpoint = f"{base_url}/api/v1/auth/internal/llm-configs/"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    endpoint,
                    params={"user_id": user_id},
                    headers={"X-Internal-Secret": internal_secret},
                )
                if response.status_code != 200:
                    logger.warning(
                        "llm.byok_fetch_failed status=%s user_id=%s",
                        response.status_code,
                        user_id,
                    )
                    return []

                payload = response.json()
        except Exception as exc:
            logger.warning("llm.byok_fetch_error user_id=%s error=%s", user_id, exc)
            return []

        configs: list[LLMConfig] = []
        for item in payload:
            provider_raw = str(item.get("provider", ""))
            provider = _parse_provider(provider_raw)
            if provider is None:
                # e.g. "anthropic", or the removed GitHub Models ("github")
                logger.warning(
                    "llm.byok_unsupported_provider provider=%s user_id=%s",
                    provider_raw,
                    user_id,
                )
                continue

            model = str(item.get("model_name", "")).strip()
            api_key = str(item.get("api_key", "")).strip()
            base_url = str(item.get("base_url", "")).strip()
            if not model or not api_key:
                continue

            if provider == LLMProvider.OPENAI and not base_url:
                base_url = "https://api.openai.com/v1"
            elif provider == LLMProvider.GROQ and not base_url:
                base_url = "https://api.groq.com/openai/v1"
            elif provider == LLMProvider.MISTRAL and not base_url:
                base_url = "https://api.mistral.ai/v1"
            elif provider == LLMProvider.GOOGLE_VERTEX and not base_url:
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai"

            if not base_url:
                # custom providers require explicit URL
                continue

            config = LLMConfig(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                max_tokens=4096,
                rpm_limit=30,
            )
            configs.append(config)
            rate_limiter.add_provider(config.provider.value, config.rpm_limit)

        return configs

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        user_id: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Generate a response using the LLM failover chain.

        Args:
            messages: List of message dicts with 'role' and 'content'
            user_id: Optional user ID for BYOK (implemented in P2-05)
            **kwargs: Additional parameters for the LLM

        Returns:
            LLMResponse with content, model_used, provider, and token counts

        Raises:
            AllProvidersDownError: If all providers fail
        """
        user_chain = await self.get_user_llm_configs(user_id or 0)
        active_chain = user_chain + MODEL_CHAIN

        if not settings.llm_failover_enabled:
            if active_chain:
                return await self._call_provider(active_chain[0], messages, **kwargs)
            raise AllProvidersDownError("No LLM providers configured")

        for config in active_chain:
            try:
                response = await self._call_provider(config, messages, **kwargs)
                logger.info(
                    "llm.success provider=%s model=%s",
                    config.provider.value,
                    config.model,
                )
                return response
            except (RateLimitError, ServiceUnavailableError, TimeoutError) as exc:
                logger.warning(
                    "llm.failover provider=%s model=%s reason=%s error=%s",
                    config.provider.value,
                    config.model,
                    _failover_reason(exc),
                    str(exc),
                )
                continue

        raise AllProvidersDownError("All LLM providers unavailable")

    async def _call_provider(
        self,
        config: LLMConfig,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Call a provider; if it rejects JSON mode, retry it once without.

        Free tiers can leave a single working provider, so a provider that
        doesn't accept response_format must not fail the review. A second
        failure raises as usual and the caller fails over.
        """
        try:
            return await self._post_chat(config, messages, **kwargs)
        except JSONModeRejectedError as exc:
            logger.warning(
                "llm.json_mode_rejected provider=%s model=%s status=%s",
                config.provider.value,
                config.model,
                exc.status,
            )
            return await self._post_chat(
                config, messages, **{**kwargs, "json_mode": False}
            )

    async def _post_chat(
        self,
        config: LLMConfig,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Call a specific LLM provider.

        Args:
            config: Provider configuration
            messages: Messages to send
            **kwargs: Additional parameters

        Returns:
            LLMResponse from the provider

        Raises:
            RateLimitError: If rate limited
            ServiceUnavailableError: If service is down
            TimeoutError: If request times out
        """
        await rate_limiter.wait_for_token(config.provider.value)

        base_url = config.base_url.rstrip("/")

        body = _request_body(config, messages, kwargs)

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                _raise_if_json_mode_rejected(config, body, response.status_code)

                if response.status_code == 429:
                    raise RateLimitError(f"Rate limited: {config.provider.value}")
                if response.status_code == 404:
                    # Usually a retired or misspelled model ID, not an outage
                    logger.error(
                        "llm.model_not_found provider=%s model=%s",
                        config.provider.value,
                        config.model,
                    )
                    raise ModelNotFoundError(
                        f"Model not found: {config.provider.value}/{config.model}"
                    )
                if response.status_code >= 500:
                    raise ServiceUnavailableError(
                        f"Service unavailable: {config.provider.value}"
                    )
                if response.status_code != 200:
                    raise ServiceUnavailableError(
                        f"Error from {config.provider.value}: {response.status_code}"
                    )

                data = response.json()
                choice = data["choices"][0]
                usage = data.get("usage", {})

                return LLMResponse(
                    content=choice["message"]["content"],
                    model_used=f"{config.provider.value}/{config.model}",
                    provider=config.provider,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )

            except httpx.TimeoutException:
                raise TimeoutError(f"Timeout calling {config.provider.value}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    raise RateLimitError(f"Rate limited: {config.provider.value}")
                raise ServiceUnavailableError(
                    f"HTTP error from {config.provider.value}: {exc.response.status_code}"
                )


def _failover_reason(exc: Exception) -> str:
    if isinstance(exc, RateLimitError):
        return "rate_limited"
    if isinstance(exc, ModelNotFoundError):
        return "model_not_found"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "unavailable"


llm_client = LLMClient()


async def check_provider_health(config: LLMConfig) -> tuple[str, bool]:
    """
    Check if a provider is healthy.

    Args:
        config: Provider configuration

    Returns:
        Tuple of (provider_name, is_healthy)
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{config.base_url.rstrip('/')}/models",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                },
            )
            return config.provider.value, response.status_code == 200
    except Exception:
        return config.provider.value, False


def model_ids(payload: Any) -> set[str]:
    """
    Model IDs from an OpenAI-style ``GET /models`` body.

    Google's OpenAI-compatible endpoint prefixes IDs with ``models/``; the
    prefix is dropped so they compare equal to the configured model names.
    """
    items = payload.get("data", []) if isinstance(payload, dict) else payload
    ids: set[str] = set()
    for item in items or []:
        model_id = item.get("id") if isinstance(item, dict) else None
        if isinstance(model_id, str):
            ids.add(model_id.removeprefix("models/"))
    return ids


async def check_model_listed(config: LLMConfig) -> bool | None:
    """
    Whether the provider's ``GET /models`` lists ``config.model``.

    Returns None when the listing can't be fetched (network error or a
    non-200), so "unreachable" stays distinct from "model not served".
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{config.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {config.api_key}"},
            )
            if response.status_code != 200:
                return None
            return config.model in model_ids(response.json())
    except Exception:
        return None


_MODEL_LISTED_CACHE: dict[tuple[str, str, str], tuple[float, bool | None]] = {}


async def cached_model_listed(config: LLMConfig) -> bool | None:
    """``check_model_listed``, cached for ``llm_health_cache_seconds``."""
    key = (config.provider.value, config.base_url, config.model)
    now = time.monotonic()
    cached = _MODEL_LISTED_CACHE.get(key)
    if cached is not None and now - cached[0] < settings.llm_health_cache_seconds:
        return cached[1]
    listed = await check_model_listed(config)
    _MODEL_LISTED_CACHE[key] = (now, listed)
    return listed


def server_provider_models() -> dict[str, str]:
    """The configured model for each server provider, keyed by provider."""
    return {
        LLMProvider.GOOGLE.value: settings.google_model,
        LLMProvider.GROQ.value: settings.groq_model,
    }
