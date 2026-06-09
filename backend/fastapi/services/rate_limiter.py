"""
Redis-backed sliding window rate limiter for LLM providers.

Enforces RPM limits shared across all uvicorn workers. Each worker
increments the same Redis counter, so the combined request rate never
exceeds the provider's actual limit.
"""

import asyncio
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Default RPM limits per provider — updated via add_provider() when
# llm_client initialises each provider from its config.
_DEFAULT_LIMITS: dict[str, int] = {
    "google": 15,
    "groq": 30,
    "github_models": 150,
}


class RedisRateLimiter:
    """
    Redis-backed fixed-window rate limiter.

    Uses one Redis key per (provider, minute-bucket). Atomic INCR
    ensures all workers share the same counter with no race conditions.
    Falls back to allowing the request if Redis is unreachable so a
    Redis outage never blocks the review pipeline entirely.
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._redis_url = redis_url or settings.redis_url
        self._client: Optional[aioredis.Redis] = None
        self._limits: dict[str, int] = dict(_DEFAULT_LIMITS)

    async def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def add_provider(self, provider: str, rpm_limit: int) -> None:
        """Register or update a provider's RPM limit."""
        self._limits[provider] = rpm_limit

    async def acquire(self, provider: str) -> bool:
        """Non-blocking check. Returns False if the window is full."""
        limit = self._limits.get(provider)
        if not limit:
            return True

        try:
            client = await self._get_client()
            key = f"ratelimit:{provider}:{int(time.time() // 60)}"
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, 60)
            return count <= limit
        except Exception as exc:
            logger.warning(
                "rate_limiter.redis_error provider=%s error=%s", provider, exc
            )
            return True

    async def wait_for_token(self, provider: str) -> None:
        """
        Wait until a token is available for the given provider.

        Increments the per-minute counter in Redis. If the window is
        already full, sleeps until the current minute window expires.
        """
        limit = self._limits.get(provider)
        if not limit:
            return

        try:
            client = await self._get_client()
            key = f"ratelimit:{provider}:{int(time.time() // 60)}"
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, 60)

            if count > limit:
                wait_seconds = 60.0 - (time.time() % 60)
                logger.info(
                    "rate_limiter.waiting provider=%s count=%d limit=%d wait=%.1fs",
                    provider,
                    count,
                    limit,
                    wait_seconds,
                )
                await asyncio.sleep(wait_seconds)
        except Exception as exc:
            logger.warning(
                "rate_limiter.redis_error provider=%s error=%s", provider, exc
            )


rate_limiter = RedisRateLimiter()
