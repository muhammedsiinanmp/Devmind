"""
Tests for the health router.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from routers.health import health_check


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_db_ok(self):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        with patch("routers.health.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = mock_session
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.health.MODEL_CHAIN", []):
                result = await health_check()

                assert result["status"] == "ok"
                assert result["db"] == "ok"

    @pytest.mark.asyncio
    async def test_health_check_db_error(self):
        with patch("routers.health.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.side_effect = Exception("DB Error")
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.health.MODEL_CHAIN", []):
                result = await health_check()

                assert result["status"] == "ok"
                assert "error" in result["db"]

    @pytest.mark.asyncio
    async def test_health_check_llm_providers(self):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        mock_config = MagicMock()
        mock_config.provider.value = "test_provider"

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("routers.health.AsyncSessionLocal") as mock_local:
            mock_local.return_value.__aenter__.return_value = mock_session
            mock_local.return_value.__aexit__.return_value = None

            with patch("routers.health.MODEL_CHAIN", [mock_config]):
                with patch("routers.health.check_provider_health") as mock_health:
                    mock_health.return_value = ("test_provider", True)

                    result = await health_check()

                    assert "llm" in result
