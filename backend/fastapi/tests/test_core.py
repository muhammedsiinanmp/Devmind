"""
Tests for core utilities.
"""

import pytest
from core.config import Settings, get_settings


class TestSettings:
    def test_settings_defaults(self):
        settings = Settings()
        assert settings.fastapi_database_url is not None
        assert settings.llm_failover_enabled is True

    def test_get_settings(self):
        settings = get_settings()
        assert settings is not None
        assert isinstance(settings, Settings)


class TestDatabase:
    @pytest.mark.asyncio
    async def test_async_session_local(self):
        from core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            assert session is not None


class TestSecurity:
    @pytest.mark.asyncio
    async def test_verify_internal_token(self):
        from core.security import verify_internal_token

        with pytest.raises(Exception):
            await verify_internal_token(None)


class TestLogging:
    def test_logging_config(self):
        from core.logging import configure_logging

        configure_logging(debug=False)
