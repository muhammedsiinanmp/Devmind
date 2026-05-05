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


def _init_model_chain() -> list[LLMConfig]:
    """Initialize the model chain with configurations."""
    return [
        LLMConfig(
            provider=LLMProvider.GOOGLE,
            model="gemini-2.0-flash",
            api_key=settings.google_ai_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            max_tokens=8192,
            rpm_limit=15,
        ),
        LLMConfig(
            provider=LLMProvider.GROQ,
            model="llama-3.1-70b-versatile",
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
            max_tokens=4096,
            rpm_limit=30,
        ),
        LLMConfig(
            provider=LLMProvider.GITHUB,
            model="gpt-4o-mini",
            api_key=settings.github_token,
            base_url="https://models.inference.ai.azure.com",
            max_tokens=4096,
            rpm_limit=150,
        ),
    ]


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
        if not settings.llm_failover_enabled:
            if MODEL_CHAIN:
                return await self._call_provider(MODEL_CHAIN[0], messages, **kwargs)
            raise AllProvidersDownError("No LLM providers configured")

        for config in MODEL_CHAIN:
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

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{config.base_url}/chat/completions",
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
                    provider=config.provider.value,
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
            response = await client.post(
                f"{config.base_url}/models",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                },
            )
            return config.provider.value, response.status_code == 200
    except Exception:
        return config.provider.value, False
