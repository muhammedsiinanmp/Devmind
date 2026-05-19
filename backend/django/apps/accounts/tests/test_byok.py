"""
BYOK (Bring Your Own Key) unit tests for UserLLMConfig.

Tests key encryption, masking, CRUD operations, and validation.
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import UserLLMConfig

User = get_user_model()


@pytest.fixture
def authed_client(db):
    """Create an authenticated test client with a user."""
    user = User.objects.create_user(
        email="byok@test.com",
        password="testpass123",
        github_id=99999,
        github_login="byokuser",
    )
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client, user


@pytest.mark.django_db
class TestLLMConfigCRUD:
    """Test CRUD operations for LLM config BYOK."""

    def test_create_config(self, authed_client):
        """Creating a config returns 201 with masked key."""
        client, user = authed_client
        resp = client.post(
            "/api/v1/auth/settings/llm/",
            {
                "name": "Test Key",
                "provider": "openai",
                "model_name": "gpt-4o",
                "api_key": "sk-test1234567890abcdef",
            },
        )
        assert resp.status_code == 201
        assert resp.data["provider"] == "openai"
        assert resp.data["model_name"] == "gpt-4o"
        # API key should not be returned in full
        assert "sk-test1234567890abcdef" not in str(resp.data)

    def test_list_configs(self, authed_client):
        """Listing configs returns all user's configs."""
        client, user = authed_client
        UserLLMConfig.objects.create(
            user=user,
            provider="openai",
            model_name="gpt-4o",
            api_key="sk-key1test123456",
        )
        resp = client.get("/api/v1/auth/settings/llm/")
        assert resp.status_code == 200
        assert len(resp.data) >= 1

    def test_get_single_config(self, authed_client):
        """Getting a single config returns its details."""
        client, user = authed_client
        config = UserLLMConfig.objects.create(
            user=user,
            provider="anthropic",
            model_name="claude-3",
            api_key="sk-ant-key123456",
        )
        resp = client.get(f"/api/v1/auth/settings/llm/{config.pk}/")
        assert resp.status_code == 200
        assert resp.data["provider"] == "anthropic"

    def test_delete_config(self, authed_client):
        """Deleting a config removes it from the database."""
        client, user = authed_client
        config = UserLLMConfig.objects.create(
            user=user,
            provider="openai",
            model_name="gpt-4o",
            api_key="sk-key3test123456",
        )
        resp = client.delete(f"/api/v1/auth/settings/llm/{config.pk}/")
        assert resp.status_code == 204
        assert not UserLLMConfig.objects.filter(pk=config.pk).exists()

    def test_patch_config_ignores_api_key(self, authed_client):
        """PATCH should not allow updating api_key."""
        client, user = authed_client
        config = UserLLMConfig.objects.create(
            user=user,
            provider="openai",
            model_name="gpt-4o",
            api_key="sk-original123456",
        )
        resp = client.patch(
            f"/api/v1/auth/settings/llm/{config.pk}/",
            {"model_name": "gpt-4o-mini", "api_key": "sk-hacked"},
            format="json",
        )
        assert resp.status_code == 200
        config.refresh_from_db()
        assert config.model_name == "gpt-4o-mini"
        assert config.api_key == "sk-original123456"

    def test_cannot_access_other_users_config(self, authed_client, db):
        """Users cannot access other users' configs."""
        client, user = authed_client
        other_user = User.objects.create_user(
            email="other@test.com",
            password="testpass123",
            github_id=88888,
            github_login="otheruser",
        )
        config = UserLLMConfig.objects.create(
            user=other_user,
            provider="openai",
            model_name="gpt-4o",
            api_key="sk-other123456",
        )
        resp = client.get(f"/api/v1/auth/settings/llm/{config.pk}/")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestKeyEncryption:
    """Test that API keys are properly encrypted and masked."""

    def test_key_stored_encrypted_and_decryptable(self, authed_client):
        """Keys should be encrypted at rest but decryptable."""
        _, user = authed_client
        config = UserLLMConfig.objects.create(
            user=user,
            provider="openai",
            model_name="gpt-4o",
            api_key="sk-plaintext123456",
        )
        config.refresh_from_db()
        # The decrypted value should match the original
        assert config.api_key == "sk-plaintext123456"

    def test_masked_key_property(self, authed_client):
        """masked_key should hide the middle of the key."""
        _, user = authed_client
        config = UserLLMConfig.objects.create(
            user=user,
            provider="openai",
            model_name="gpt-4o",
            api_key="sk-abcdefghijklmnop",
        )
        masked = config.masked_key
        # Should start with sk- prefix and contain masking
        assert masked.startswith("sk-")
        assert "***" in masked
        # Should not contain the full key
        assert masked != "sk-abcdefghijklmnop"

    def test_short_key_fully_masked(self, authed_client):
        """Very short keys should be fully masked."""
        _, user = authed_client
        config = UserLLMConfig.objects.create(
            user=user,
            provider="custom",
            model_name="model",
            api_key="short",
        )
        masked = config.masked_key
        assert masked == "***"


@pytest.mark.django_db
class TestPriority:
    """Test LLM config priority/ordering."""

    def test_unique_constraint_per_user_provider_model(self, authed_client):
        """Cannot create duplicate provider+model for same user."""
        _, user = authed_client
        UserLLMConfig.objects.create(
            user=user,
            provider="openai",
            model_name="gpt-4o",
            api_key="sk-keya123456",
        )
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            UserLLMConfig.objects.create(
                user=user,
                provider="openai",
                model_name="gpt-4o",
                api_key="sk-keyb123456",
            )
