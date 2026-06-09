"""
Tests for the Redis-backed rate limiter.
"""

import pytest
import fakeredis.aioredis as fakeredis

from services.rate_limiter import RedisRateLimiter


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def limiter(fake_redis):
    rl = RedisRateLimiter(redis_url="redis://unused")
    rl._client = fake_redis
    return rl


class TestRedisRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_within_limit(self, limiter):
        limiter.add_provider("test_provider", 10)
        result = await limiter.acquire("test_provider")
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_exceeds_limit(self, limiter):
        limiter.add_provider("tight", 2)
        await limiter.acquire("tight")
        await limiter.acquire("tight")
        result = await limiter.acquire("tight")
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_unknown_provider_always_true(self, limiter):
        result = await limiter.acquire("nonexistent_provider")
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_token_within_limit(self, limiter):
        """wait_for_token should return immediately when under limit."""
        limiter.add_provider("fast", 100)
        await limiter.wait_for_token("fast")

    @pytest.mark.asyncio
    async def test_wait_for_token_unknown_provider(self, limiter):
        """Unknown provider — should return immediately without error."""
        await limiter.wait_for_token("unknown")

    @pytest.mark.asyncio
    async def test_add_provider_updates_limit(self, limiter):
        limiter.add_provider("prov", 5)
        assert limiter._limits["prov"] == 5
        limiter.add_provider("prov", 20)
        assert limiter._limits["prov"] == 20

    @pytest.mark.asyncio
    async def test_counters_are_shared_across_instances(self, fake_redis):
        """Two limiter instances sharing the same Redis client share the counter."""
        a = RedisRateLimiter(redis_url="redis://unused")
        a._client = fake_redis
        a.add_provider("shared", 3)

        b = RedisRateLimiter(redis_url="redis://unused")
        b._client = fake_redis
        b.add_provider("shared", 3)

        await a.acquire("shared")
        await a.acquire("shared")
        await a.acquire("shared")
        # Fourth call across both instances — limit is 3, so this returns False
        result = await b.acquire("shared")
        assert result is False

    @pytest.mark.asyncio
    async def test_redis_failure_falls_back_to_allow(self, limiter, monkeypatch):
        """Redis outage must not block the review pipeline."""

        async def _bad_incr(*_, **__):
            raise ConnectionError("redis down")

        monkeypatch.setattr(limiter._client, "incr", _bad_incr)
        limiter.add_provider("fallback_prov", 1)

        result = await limiter.acquire("fallback_prov")
        assert result is True
