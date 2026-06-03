"""
LLM Client with automatic failover chain.

Supports multiple LLM providers:
1. Google Gemini (primary)
2. Groq (fallback)
3. GitHub Models (emergency fallback)

Automatically fails over on rate limits, service unavailable, or timeout.
"""

import logging
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
    GITHUB = "github"
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


def _parse_provider(provider: str) -> LLMProvider | None:
    mapping = {
        "google": LLMProvider.GOOGLE,
        "groq": LLMProvider.GROQ,
        "github": LLMProvider.GITHUB,
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
                model="gemini-2.0-flash",
                api_key=settings.google_ai_api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                max_tokens=8192,
                rpm_limit=15,
            )
        )

    if settings.groq_api_key:
        chain.append(
            LLMConfig(
                provider=LLMProvider.GROQ,
                model="llama-3.3-70b-versatile",
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
                max_tokens=4096,
                rpm_limit=30,
            )
        )

    if settings.github_token:
        chain.append(
            LLMConfig(
                provider=LLMProvider.GITHUB,
                model="gpt-4o-mini",
                api_key=settings.github_token,
                base_url="https://models.inference.ai.azure.com",
                max_tokens=4096,
                rpm_limit=150,
            )
        )

    return chain


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
                    "llm.failover provider=%s model=%s error=%s",
                    config.provider.value,
                    config.model,
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

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": config.model,
                        "messages": messages,
                        "max_tokens": kwargs.get("max_tokens", config.max_tokens),
                        "temperature": kwargs.get("temperature", 0.7),
                    },
                )

                if response.status_code == 429:
                    raise RateLimitError(f"Rate limited: {config.provider.value}")
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
