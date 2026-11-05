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
    LLMConfig,
)


@pytest.fixture(autouse=True)
def mock_model_chain(monkeypatch):
    from services import llm_client

    monkeypatch.setattr(llm_client.settings, "google_ai_api_key", "mock-google-key")
    monkeypatch.setattr(llm_client.settings, "groq_api_key", "mock-groq-key")
    monkeypatch.setattr(llm_client.settings, "github_token", "mock-github-token")
    monkeypatch.setattr(llm_client.settings, "github_models_enabled", True)
    new_chain = llm_client._init_model_chain()
    monkeypatch.setattr(llm_client, "MODEL_CHAIN", new_chain)
    import tests.test_llm_client

    monkeypatch.setattr(tests.test_llm_client, "MODEL_CHAIN", new_chain)
    yield


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


class TestBYOKPriority:
    @pytest.mark.asyncio
    async def test_user_configs_are_tried_before_default_chain(self, mock_messages):
        client = LLMClient()
        user_cfg = LLMConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
            max_tokens=4096,
            rpm_limit=30,
        )

        with (
            patch.object(
                client, "get_user_llm_configs", AsyncMock(return_value=[user_cfg])
            ),
            patch.object(client, "_call_provider", AsyncMock()) as mock_call_provider,
        ):
            # fail user config once, then succeed on first default provider
            mock_call_provider.side_effect = [
                RateLimitError("rate limit"),
                MagicMock(
                    content="ok",
                    model_used="google/gemini-2.0-flash",
                    provider="google",
                    prompt_tokens=1,
                    completion_tokens=1,
                ),
            ]

            await client.generate(mock_messages, user_id=123)

            first_call_cfg = mock_call_provider.call_args_list[0].args[0]
            assert first_call_cfg.provider == LLMProvider.OPENAI


class TestCheckProviderHealth:
    @pytest.mark.asyncio
    async def test_check_provider_health_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = mock_response

            provider, is_healthy = await check_provider_health(MODEL_CHAIN[0])

            assert provider == "google"
            assert is_healthy is True

    @pytest.mark.asyncio
    async def test_check_provider_health_failure(self):
        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.side_effect = Exception("Network error")

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


def _post_returning(statuses):
    responses = iter(statuses)

    def post(*args, **kwargs):
        mock = MagicMock(status_code=next(responses))
        mock.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        return mock

    return post


class TestModelSettings:
    def test_models_and_base_url_come_from_settings(self, monkeypatch):
        from services import llm_client as module

        monkeypatch.setattr(module.settings, "google_model", "gemini-test-model")
        monkeypatch.setattr(module.settings, "groq_model", "groq/test-model")
        monkeypatch.setattr(module.settings, "github_models_model", "pub/test-model")
        monkeypatch.setattr(
            module.settings, "github_models_base_url", "https://models.example/inf"
        )

        chain = module._init_model_chain()

        assert [(c.provider, c.model) for c in chain] == [
            (LLMProvider.GOOGLE, "gemini-test-model"),
            (LLMProvider.GROQ, "groq/test-model"),
            (LLMProvider.GITHUB, "pub/test-model"),
        ]
        assert chain[2].base_url == "https://models.example/inf"

    def test_defaults_are_current_pinned_models(self):
        from core.config import Settings

        defaults = Settings(_env_file=None)
        assert defaults.google_model == "gemini-2.5-flash"
        assert defaults.groq_model == "openai/gpt-oss-120b"
        assert defaults.github_models_enabled is False
        assert defaults.github_models_base_url == "https://models.github.ai/inference"

    def test_github_models_skipped_unless_enabled(self, monkeypatch):
        from services import llm_client as module

        monkeypatch.setattr(module.settings, "github_models_enabled", False)

        chain = module._init_model_chain()

        assert [c.provider for c in chain] == [LLMProvider.GOOGLE, LLMProvider.GROQ]

    @pytest.mark.asyncio
    async def test_request_uses_configured_model_and_base_url(self, mock_messages):
        client = LLMClient()

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = _post_returning([200])

            result = await client.generate(mock_messages)

        url = mock_instance.post.call_args.args[0]
        body = mock_instance.post.call_args.kwargs["json"]
        assert url == f"{MODEL_CHAIN[0].base_url}/chat/completions"
        assert body["model"] == MODEL_CHAIN[0].model
        assert result.model_used == f"google/{MODEL_CHAIN[0].model}"


class TestModelNotFound:
    @pytest.mark.asyncio
    async def test_404_is_logged_as_model_not_found_and_fails_over(
        self, mock_messages, caplog
    ):
        client = LLMClient()

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = _post_returning([404, 200])

            with caplog.at_level("INFO", logger="services.llm_client"):
                result = await client.generate(mock_messages)

        assert "groq" in result.model_used
        messages = [r.getMessage() for r in caplog.records]
        google_model = MODEL_CHAIN[0].model
        assert any(
            "llm.model_not_found" in m and f"model={google_model}" in m
            for m in messages
        )
        failover = [m for m in messages if "llm.failover" in m]
        assert len(failover) == 1
        assert "reason=model_not_found" in failover[0]
        assert "rate_limited" not in failover[0]

    @pytest.mark.asyncio
    async def test_429_is_logged_as_rate_limited_not_model_not_found(
        self, mock_messages, caplog
    ):
        client = LLMClient()

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = _post_returning([429, 200])

            with caplog.at_level("INFO", logger="services.llm_client"):
                await client.generate(mock_messages)

        messages = [r.getMessage() for r in caplog.records]
        assert not any("model_not_found" in m for m in messages)
        assert any("llm.failover" in m and "reason=rate_limited" in m for m in messages)


class TestModelListing:
    def test_model_ids_strips_google_prefix(self):
        from services.llm_client import model_ids

        payload = {
            "data": [{"id": "models/gemini-2.5-flash"}, {"id": "openai/gpt-oss-120b"}]
        }
        assert model_ids(payload) == {"gemini-2.5-flash", "openai/gpt-oss-120b"}

    @pytest.mark.asyncio
    async def test_check_model_listed(self):
        from services.llm_client import check_model_listed

        model = MODEL_CHAIN[0].model
        listing = MagicMock(status_code=200)
        listing.json.return_value = {"data": [{"id": f"models/{model}"}]}

        with patch("services.llm_client.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = listing

            assert await check_model_listed(MODEL_CHAIN[0]) is True
            listing.json.return_value = {"data": [{"id": "models/other"}]}
            assert await check_model_listed(MODEL_CHAIN[0]) is False
            mock_instance.get.return_value = MagicMock(status_code=401)
            assert await check_model_listed(MODEL_CHAIN[0]) is None

    @pytest.mark.asyncio
    async def test_cached_model_listed_caches_results(self, monkeypatch):
        from services import llm_client as module

        monkeypatch.setattr(module, "_MODEL_LISTED_CACHE", {})
        check = AsyncMock(return_value=True)
        monkeypatch.setattr(module, "check_model_listed", check)

        assert await module.cached_model_listed(MODEL_CHAIN[0]) is True
        assert await module.cached_model_listed(MODEL_CHAIN[0]) is True
        assert check.await_count == 1

        monkeypatch.setattr(module.settings, "llm_health_cache_seconds", 0)
        await module.cached_model_listed(MODEL_CHAIN[0])
        assert check.await_count == 2
