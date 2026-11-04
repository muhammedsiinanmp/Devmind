import os

# Isolate the test run from the developer's real environment. This must run
# before any app module is imported, because settings are read (and cached)
# at import time.
os.environ["DEVMIND_ENV_FILE"] = ""
os.environ["SENTRY_DSN_FASTAPI"] = ""
os.environ["SENTRY_ENVIRONMENT"] = "test"
os.environ["FASTAPI_INTERNAL_SECRET"] = "test-internal-secret"
os.environ["GOOGLE_AI_API_KEY"] = "test-google-key"
os.environ["GROQ_API_KEY"] = "test-groq-key"
os.environ["GITHUB_TOKEN"] = "test-github-token"
os.environ["OPENAI_API_KEY"] = ""

import pytest  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
