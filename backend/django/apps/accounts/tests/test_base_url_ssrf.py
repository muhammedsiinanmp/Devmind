"""
BYOK base_url must not let a user make the server call internal addresses
(SSRF). Only https URLs whose host resolves to public IPs are accepted.
"""

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import UserLLMConfig

User = get_user_model()

# Literal IPs resolve without network access, so these tests are offline-safe.
PUBLIC_HTTPS_URL = "https://93.184.216.34/v1"

BLOCKED_URLS = [
    "http://93.184.216.34/v1",  # not https
    "ftp://93.184.216.34/v1",  # not https
    "https://127.0.0.1:8001/v1",  # loopback
    "https://localhost/v1",  # loopback by name
    "https://10.0.0.5/v1",  # private
    "https://192.168.1.10/v1",  # private
    "https://169.254.169.254/latest/meta-data",  # link-local (cloud metadata)
    "https://0.0.0.0/v1",  # unspecified
    "https://224.0.0.1/v1",  # multicast
    "https://[::1]/v1",  # IPv6 loopback
    "https://[::ffff:127.0.0.1]/v1",  # IPv4-mapped loopback
    "https://no-such-host.invalid/v1",  # does not resolve
]


@pytest.fixture
def authed_client(db):
    user = User.objects.create_user(
        email="ssrf@test.com",
        password="testpass123",
        github_id=424242,
        github_login="ssrfuser",
    )
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client, user


def _mock_outbound(mocker, status_code=200, side_effect=None):
    """Patch the outbound HTTP client; returns the mock .get() for assertions."""
    mock_http_client = mocker.MagicMock()
    if side_effect is not None:
        mock_http_client.get.side_effect = side_effect
    else:
        mock_http_client.get.return_value = mocker.Mock(status_code=status_code)
    mocker.patch(
        "apps.accounts.views.httpx.Client"
    ).return_value.__enter__.return_value = mock_http_client
    return mock_http_client.get


@pytest.mark.django_db
class TestCreateConfigBaseUrl:
    @pytest.mark.parametrize("base_url", BLOCKED_URLS)
    def test_create_rejects_unsafe_base_url(self, authed_client, base_url):
        client, user = authed_client
        resp = client.post(
            "/api/v1/settings/llm/",
            {
                "provider": "custom",
                "model_name": "m",
                "api_key": "sk-test",
                "base_url": base_url,
            },
            format="json",
        )
        assert resp.status_code == 400
        assert "base_url" in resp.data
        assert not UserLLMConfig.objects.filter(user=user).exists()

    def test_create_accepts_public_https_base_url(self, authed_client):
        client, user = authed_client
        resp = client.post(
            "/api/v1/settings/llm/",
            {
                "provider": "custom",
                "model_name": "m",
                "api_key": "sk-test",
                "base_url": PUBLIC_HTTPS_URL,
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["base_url"] == PUBLIC_HTTPS_URL

    def test_create_without_base_url_still_works(self, authed_client):
        client, _user = authed_client
        resp = client.post(
            "/api/v1/settings/llm/",
            {"provider": "openai", "model_name": "gpt-4o", "api_key": "sk-test"},
            format="json",
        )
        assert resp.status_code == 201

    @override_settings(SKIP_LLM_KEY_VALIDATION=False)
    def test_create_does_not_call_unsafe_url(self, authed_client, mocker):
        client, _user = authed_client
        outbound_get = _mock_outbound(mocker)
        resp = client.post(
            "/api/v1/settings/llm/",
            {
                "provider": "custom",
                "model_name": "m",
                "api_key": "sk-test",
                "base_url": "https://169.254.169.254/latest",
            },
            format="json",
        )
        assert resp.status_code == 400
        outbound_get.assert_not_called()


@pytest.mark.django_db
class TestPatchConfigBaseUrl:
    def test_patch_rejects_unsafe_base_url(self, authed_client):
        client, user = authed_client
        config = UserLLMConfig.objects.create(
            user=user, provider="custom", model_name="m", api_key="sk-test"
        )
        resp = client.patch(
            f"/api/v1/settings/llm/{config.pk}/",
            {"base_url": "https://127.0.0.1/v1"},
            format="json",
        )
        assert resp.status_code == 400
        config.refresh_from_db()
        assert config.base_url == ""


@pytest.mark.django_db
class TestTestEndpointBaseUrl:
    @pytest.mark.parametrize("base_url", BLOCKED_URLS)
    def test_test_endpoint_rejects_unsafe_base_url(
        self, authed_client, mocker, base_url
    ):
        client, _user = authed_client
        outbound_get = _mock_outbound(mocker)
        resp = client.post(
            "/api/v1/settings/llm/test/",
            {
                "provider": "custom",
                "model_name": "m",
                "api_key": "sk-test",
                "base_url": base_url,
            },
            format="json",
        )
        assert resp.status_code == 400
        outbound_get.assert_not_called()

    def test_test_endpoint_calls_public_https_base_url(self, authed_client, mocker):
        client, _user = authed_client
        outbound_get = _mock_outbound(mocker, status_code=200)
        resp = client.post(
            "/api/v1/settings/llm/test/",
            {
                "provider": "custom",
                "model_name": "m",
                "api_key": "sk-test",
                "base_url": PUBLIC_HTTPS_URL,
            },
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["status"] == "ok"
        assert outbound_get.call_args.args[0] == f"{PUBLIC_HTTPS_URL}/models"

    def test_test_endpoint_does_not_leak_exception_text(self, authed_client, mocker):
        client, _user = authed_client
        detail = "connect failed to internal-db.corp:5432 secret-token-xyz"
        _mock_outbound(mocker, side_effect=httpx.ConnectError(detail))
        resp = client.post(
            "/api/v1/settings/llm/test/",
            {"provider": "openai", "model_name": "gpt-4o", "api_key": "sk-test"},
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["error"] == "http_error"
        assert detail not in str(resp.data)

    def test_test_endpoint_does_not_leak_unexpected_exception_text(
        self, authed_client, mocker
    ):
        client, _user = authed_client
        detail = "boom: /etc/devmind/secret.key"
        _mock_outbound(mocker, side_effect=RuntimeError(detail))
        resp = client.post(
            "/api/v1/settings/llm/test/",
            {"provider": "openai", "model_name": "gpt-4o", "api_key": "sk-test"},
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["error"] == "unknown"
        assert detail not in str(resp.data)
