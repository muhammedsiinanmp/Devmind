"""
Tests for the health router.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _session_with_pgvector(version):
    session = AsyncMock()
    ext_row = MagicMock()
    ext_row.scalar_one_or_none.return_value = version
    # First execute() is SELECT 1, second is the pg_extension lookup
    session.execute = AsyncMock(side_effect=[MagicMock(), ext_row])
    return session


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_db_ok(self, client):
        session = _session_with_pgvector("0.7.0")

        with patch("routers.health.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = session
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.health.MODEL_CHAIN", []):
                response = await client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["pgvector"] == "ok (0.7.0)"

    @pytest.mark.asyncio
    async def test_health_check_pgvector_missing_is_degraded(self, client):
        session = _session_with_pgvector(None)

        with patch("routers.health.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = session
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.health.MODEL_CHAIN", []):
                response = await client.get("/health")

        assert response.status_code == 503
        assert response.json()["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_check_db_error_is_degraded(self, client):
        with patch("routers.health.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.side_effect = Exception("DB Error")
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.health.MODEL_CHAIN", []):
                response = await client.get("/health")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["database"] == "error"

    @pytest.mark.asyncio
    async def test_health_check_db_error_does_not_leak_exception_text(self, client):
        secret_detail = "password authentication failed for user devmind@10.0.0.5"
        with patch("routers.health.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.side_effect = Exception(secret_detail)
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.health.MODEL_CHAIN", []):
                response = await client.get("/health")

        assert secret_detail not in response.text
        assert "10.0.0.5" not in response.text

    @pytest.mark.asyncio
    async def test_health_check_llm_providers(self, client):
        session = _session_with_pgvector("0.7.0")
        mock_config = MagicMock()
        mock_config.provider.value = "test_provider"
        mock_config.model = "test-model"

        with patch("routers.health.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = session
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.health.MODEL_CHAIN", [mock_config]):
                with patch(
                    "routers.health.cached_model_listed", AsyncMock(return_value=None)
                ):
                    response = await client.get("/health")

        # LLM reachability is informational and must not fail the health check
        assert response.status_code == 200
        assert response.json()["checks"]["llm_test_provider"] == "unreachable"

    @pytest.mark.asyncio
    async def test_health_reports_configured_model_and_listing(self, client):
        from services.llm_client import LLMConfig, LLMProvider

        session = _session_with_pgvector("0.7.0")
        google = LLMConfig(
            provider=LLMProvider.GOOGLE,
            model="gemini-2.5-flash",
            api_key="health-test-key-value",
            base_url="https://google.example",
            max_tokens=10,
            rpm_limit=1,
        )
        groq = LLMConfig(
            provider=LLMProvider.GROQ,
            model="retired-model",
            api_key="health-test-key-value",
            base_url="https://groq.example",
            max_tokens=10,
            rpm_limit=1,
        )
        listed = AsyncMock(side_effect=[True, False])

        with patch("routers.health.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = session
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.health.MODEL_CHAIN", [google, groq]):
                with patch("routers.health.cached_model_listed", listed):
                    response = await client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["checks"]["llm_google"] == "ok"
        assert body["checks"]["llm_groq"] == "model_not_listed"
        assert body["llm"]["google"] == {
            "model": "gemini-2.5-flash",
            "enabled": True,
            "listed": True,
        }
        assert body["llm"]["groq"]["listed"] is False
        # GitHub Models is off by default: model reported, not checked
        assert body["llm"]["github"]["enabled"] is False
        assert body["llm"]["github"]["listed"] is None
        assert "health-test-key-value" not in response.text
