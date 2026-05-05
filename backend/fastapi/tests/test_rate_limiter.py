"""
Tests for the rate limiter service.
"""

import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from services.rate_limiter import TokenBucket, RateLimiter, rate_limiter


class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_acquire_tokens_available(self):
        bucket = TokenBucket(capacity=10, refill_rate=5.0)
        result = await bucket.acquire(5)
        assert result is True
        assert bucket.tokens == 5

    @pytest.mark.asyncio
    async def test_acquire_tokens_not_available(self):
        bucket = TokenBucket(capacity=10, refill_rate=5.0)
        await bucket.acquire(10)
        result = await bucket.acquire(1)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_token(self):
        bucket = TokenBucket(capacity=10, refill_rate=0.1)
        await bucket.acquire(10)
        asyncio.create_task(bucket.wait_for_token(1))
        await asyncio.sleep(0.5)


class TestRateLimiter:
    def test_add_provider(self):
        limiter = RateLimiter()
        limiter.add_provider("test", 100)
        bucket = limiter.get_bucket("test")
        assert bucket is not None
        assert bucket.capacity == 100

    def test_get_bucket_not_found(self):
        limiter = RateLimiter()
        bucket = limiter.get_bucket("nonexistent")
        assert bucket is None

    @pytest.mark.asyncio
    async def test_acquire_no_provider(self):
        limiter = RateLimiter()
        result = await limiter.acquire("unknown")
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_token_no_provider(self):
        limiter = RateLimiter()
        await limiter.wait_for_token("unknown")
