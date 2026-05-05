"""
Token bucket rate limiter for LLM providers.

Enforces RPM (requests per minute) limits per provider.
"""

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """
    Token bucket rate limiter implementation.

    Attributes:
        capacity: Maximum tokens in the bucket (e.g., RPM)
        refill_rate: Tokens added per second (capacity / 60)
        tokens: Current number of tokens available
        last_refill: Timestamp of last refill
    """

    capacity: int
    refill_rate: float
    tokens: float = field(default_factory=lambda: float("inf"))
    last_refill: float = field(default_factory=time.time)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        self.tokens = float(self.capacity)

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens from the bucket.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens were acquired, False if rate limited
        """
        async with self._lock:
            await self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    async def _refill(self) -> None:
        """Refill tokens based on time elapsed since last refill."""
        now = time.time()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.refill_rate

        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now

    async def wait_for_token(self, tokens: int = 1) -> None:
        """
        Wait until tokens are available.

        Args:
            tokens: Number of tokens needed
        """
        while not await self.acquire(tokens):
            await asyncio.sleep(0.1)


class RateLimiter:
    """
    Rate limiter for multiple LLM providers.

    Manages token buckets per provider to enforce RPM limits.
    """

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}

    def add_provider(self, provider: str, rpm_limit: int) -> None:
        """
        Add a provider with its RPM limit.

        Args:
            provider: Provider name
            rpm_limit: Requests per minute limit
        """
        self._buckets[provider] = TokenBucket(
            capacity=rpm_limit,
            refill_rate=rpm_limit / 60.0,
        )

    async def acquire(self, provider: str, tokens: int = 1) -> bool:
        """
        Try to acquire tokens for a provider.

        Args:
            provider: Provider name
            tokens: Number of tokens to acquire

        Returns:
            True if acquired, False if rate limited
        """
        bucket = self._buckets.get(provider)
        if not bucket:
            return True
        return await bucket.acquire(tokens)

    async def wait_for_token(self, provider: str, tokens: int = 1) -> None:
        """
        Wait until tokens are available for a provider.

        Args:
            provider: Provider name
            tokens: Number of tokens needed
        """
        bucket = self._buckets.get(provider)
        if bucket:
            await bucket.wait_for_token(tokens)

    def get_bucket(self, provider: str) -> TokenBucket | None:
        """Get the token bucket for a provider."""
        return self._buckets.get(provider)


rate_limiter = RateLimiter()
