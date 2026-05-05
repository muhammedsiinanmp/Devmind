"""
Tests for the LLM client with failover chain.

Tests match acceptance criteria from P2-04:
- Primary provider (Google) succeeds on first try
- Mock Google to return 429 → client falls over to Groq automatically
- Mock Google + Groq to fail → client uses GitHub Models
- Mock all three to fail → raises AllProvidersDownError
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.llm_client import (
    AllProvidersDownError,
    LLMClient,
    LLMProvider,
    MODEL_CHAIN,
    RateLimitError,
    ServiceUnavailableError,
    TimeoutError,
    check_provider_health,
)


@pytest.fixture
def llm_client():
    return LLMClient()


@pytest.fixture
def mock_messages():
    return [{"role": "user", "content": "Hello"}]


class TestProviderEnum:
    def test_provider_values(self):
        assert LLMProvider.GOOGLE.value == "google"
        assert LLMProvider.GROQ.value == "groq"
        assert LLMProvider.GITHUB.value == "github"


class TestModelChain:
    def test_model_chain_has_three_providers(self):
        assert len(MODEL_CHAIN) == 3

    def test_model_chain_order(self):
        assert MODEL_CHAIN[0].provider == LLMProvider.GOOGLE
        assert MODEL_CHAIN[1].provider == LLMProvider.GROQ
        assert MODEL_CHAIN[2].provider == LLMProvider.GITHUB


class TestLLMClientSuccess:
    @pytest.mark.asyncio
    async def test_primary_provider_succeeds(self, llm_client, mock_messages):
        mock_response = {
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = mock_response

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response_obj

            result = await llm_client.generate(mock_messages)

            assert result.content == "Hello!"
            assert "google" in result.model_used

    @pytest.mark.asyncio
    async def test_generate_returns_model_used(self, llm_client, mock_messages):
        mock_response = {
            "choices": [{"message": {"content": "Response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json.return_value = mock_response

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response_obj

            result = await llm_client.generate(mock_messages)

            assert result.model_used is not None
            assert "/" in result.model_used


class TestFailoverChain:
    @pytest.mark.asyncio
    async def test_fallback_on_rate_limit(self, mock_messages):
        client = LLMClient()
        call_count = 0

        def create_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_response = {
                "choices": [{"message": {"content": f"Response {call_count}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

            mock = MagicMock()
            mock.status_code = 429 if call_count == 1 else 200
            mock.json.return_value = mock_response
            return mock

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = create_response

            result = await client.generate(mock_messages)

            assert call_count == 2
            assert result.content == "Response 2"
            assert "groq" in result.model_used

    @pytest.mark.asyncio
    async def test_fallback_to_github_when_google_and_groq_fail(self, mock_messages):
        client = LLMClient()
        call_count = 0

        def create_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            mock_response = {
                "choices": [{"message": {"content": f"Response {call_count}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

            mock = MagicMock()
            if call_count < 3:
                mock.status_code = 429
            else:
                mock.status_code = 200
            mock.json.return_value = mock_response
            return mock

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = create_response

            result = await client.generate(mock_messages)

            assert call_count == 3
            assert "github" in result.model_used


class TestAllProvidersDown:
    @pytest.mark.asyncio
    async def test_raises_all_providers_down_error(self, mock_messages):
        client = LLMClient()

        def mock_post(*args, **kwargs):
            mock = MagicMock()
            mock.status_code = 429
            return mock

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = mock_post

            with pytest.raises(AllProvidersDownError):
                await client.generate(mock_messages)


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_rate_limiter_import(self):
        from services.rate_limiter import rate_limiter, TokenBucket

        bucket = TokenBucket(capacity=10, refill_rate=0.5)
        assert bucket.capacity == 10

        assert rate_limiter is not None


class TestCheckProviderHealth:
    @pytest.mark.asyncio
    async def test_check_provider_health_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response

            provider, is_healthy = await check_provider_health(MODEL_CHAIN[0])

            assert provider == "google"
            assert is_healthy is True

    @pytest.mark.asyncio
    async def test_check_provider_health_failure(self):
        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = Exception("Network error")

            provider, is_healthy = await check_provider_health(MODEL_CHAIN[0])

            assert provider == "google"
            assert is_healthy is False


class TestErrorClasses:
    def test_rate_limit_error(self):
        with pytest.raises(RateLimitError):
            raise RateLimitError("Rate limited")

    def test_service_unavailable_error(self):
        with pytest.raises(ServiceUnavailableError):
            raise ServiceUnavailableError("Service down")

    def test_timeout_error(self):
        with pytest.raises(TimeoutError):
            raise TimeoutError("Timeout")

    def test_all_providers_down_error(self):
        with pytest.raises(AllProvidersDownError):
            raise AllProvidersDownError("All down")
