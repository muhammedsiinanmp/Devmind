from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.repositories.tests.factories import RepositoryFactory, UserFactory


@pytest.fixture
def auth_client(db: None) -> tuple[APIClient, Any]:
    user = UserFactory()
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestRepositoryListView:
    def test_unauthenticated_returns_401(self) -> None:
        client = APIClient()
        response = client.get("/api/v1/repositories/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_only_users_repos(self, auth_client: tuple[APIClient, Any]) -> None:
        client, user = auth_client
        RepositoryFactory(owner=user)
        RepositoryFactory(owner=user)
        RepositoryFactory()  # Different user
        response = client.get("/api/v1/repositories/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 2  # type: ignore[index]

    def test_excludes_inactive_repos(self, auth_client: tuple[APIClient, Any]) -> None:
        client, user = auth_client
        RepositoryFactory(owner=user, is_active=True)
        RepositoryFactory(owner=user, is_active=False)
        response = client.get("/api/v1/repositories/")
        assert response.data["count"] == 1  # type: ignore[index]

    def test_can_filter_by_review_enabled(
        self, auth_client: tuple[APIClient, Any]
    ) -> None:
        client, user = auth_client
        RepositoryFactory(owner=user, review_enabled=True)
        RepositoryFactory(owner=user, review_enabled=False)
        response = client.get("/api/v1/repositories/?review_enabled=true")
        assert response.data["count"] == 1  # type: ignore[index]


@pytest.mark.django_db
class TestRepositoryDetailView:
    def test_returns_repository(self, auth_client: tuple[APIClient, Any]) -> None:
        client, user = auth_client
        repo = RepositoryFactory(owner=user)
        response = client.get(f"/api/v1/repositories/{repo.pk}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["full_name"] == repo.full_name  # type: ignore[index]

    def test_cannot_access_other_users_repo(
        self, auth_client: tuple[APIClient, Any]
    ) -> None:
        client, _user = auth_client
        other_repo = RepositoryFactory()  # Different owner
        response = client.get(f"/api/v1/repositories/{other_repo.pk}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_toggle_review_enabled(self, auth_client: tuple[APIClient, Any]) -> None:
        client, user = auth_client
        repo = RepositoryFactory(owner=user, review_enabled=True)
        response = client.patch(
            f"/api/v1/repositories/{repo.pk}/",
            {"review_enabled": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        repo.refresh_from_db()
        assert repo.review_enabled is False


@pytest.mark.django_db
class TestWebhookView:
    def _signed_post(
        self,
        client: APIClient,
        payload: dict[str, Any],
        secret: str,
        event: str = "pull_request",
    ) -> Any:
        body = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return client.post(
            "/api/v1/webhooks/github/",
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=sig,
            HTTP_X_GITHUB_EVENT=event,
        )

    def test_valid_webhook_returns_200(self, settings: Any, mocker: Any) -> None:
        settings.GITHUB_WEBHOOK_SECRET = "test-secret"
        mocker.patch("apps.repositories.views.WebhookDispatcher.dispatch")
        client = APIClient()
        response = self._signed_post(client, {"action": "opened"}, "test-secret")
        assert response.status_code == status.HTTP_200_OK

    def test_invalid_signature_returns_403(self, settings: Any) -> None:
        settings.GITHUB_WEBHOOK_SECRET = "correct-secret"
        client = APIClient()
        response = self._signed_post(client, {"action": "opened"}, "wrong-secret")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_signature_returns_403(self, settings: Any) -> None:
        settings.GITHUB_WEBHOOK_SECRET = "test-secret"
        client = APIClient()
        response = client.post(
            "/api/v1/webhooks/github/",
            data={"action": "opened"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestConnectRepositoryView:
    def test_enqueues_sync_task_on_connect(
        self, auth_client: tuple[APIClient, Any], mocker: MagicMock
    ) -> None:
        client, user = auth_client
        mock_task = mocker.patch(
            "apps.repositories.views.initial_repository_sync_task.delay"
        )
        response = client.post("/api/v1/repositories/connect/")
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_task.assert_called_once_with(user_id=user.pk)
