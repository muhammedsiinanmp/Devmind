from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.repositories.models import Repository
from apps.repositories.tasks import (
    initial_repository_sync_task,
    install_webhook_task,
    remove_webhook_task,
)
from apps.repositories.tests.factories import RepositoryFactory, UserFactory
from apps.repositories.types import GitHubRepoData, WebhookInstallResult


@pytest.fixture
def mock_github_service(mocker: MagicMock) -> MagicMock:
    mock = mocker.patch("apps.repositories.tasks.GitHubService")
    # Provide a real return value so Django ORM doesn't choke on MagicMock
    mock.return_value.install_webhook.return_value = WebhookInstallResult(
        webhook_id=123, ping_url="https://...", events=["pull_request"]
    )
    return mock


@pytest.mark.django_db(transaction=True)
class TestInitialRepositorySyncTask:
    def test_creates_repositories_for_user(
        self, mock_github_service: MagicMock
    ) -> None:
        user = UserFactory()
        fake_repo = GitHubRepoData(
            github_id=111,
            full_name="acme/api",
            name="api",
            owner_login="acme",
            description="test",
            is_private=False,
            default_branch="main",
            html_url="https://github.com/acme/api",
            clone_url="https://github.com/acme/api.git",
            language="Python",
            stargazers_count=1,
        )
        mock_github_service.return_value.fetch_user_repositories.return_value = [
            fake_repo
        ]

        initial_repository_sync_task(user_id=user.pk)

        assert Repository.objects.filter(owner=user, github_id=111).exists()

    def test_updates_existing_repository_metadata(
        self, mock_github_service: MagicMock
    ) -> None:
        user = UserFactory()
        existing = RepositoryFactory(owner=user, github_id=222, stargazers_count=5)

        updated_repo = GitHubRepoData(
            github_id=222,
            full_name="acme/api",
            name="api",
            owner_login="acme",
            description="updated",
            is_private=False,
            default_branch="main",
            html_url="https://github.com/acme/api",
            clone_url="https://github.com/acme/api.git",
            language="Python",
            stargazers_count=100,  # updated
        )
        mock_github_service.return_value.fetch_user_repositories.return_value = [
            updated_repo
        ]

        initial_repository_sync_task(user_id=user.pk)

        existing.refresh_from_db()
        assert existing.stargazers_count == 100

    def test_sets_last_synced_at(self, mock_github_service: MagicMock) -> None:
        user = UserFactory()
        repo = RepositoryFactory(owner=user, github_id=333, last_synced_at=None)
        fake_repo = GitHubRepoData(
            github_id=333,
            full_name=repo.full_name,
            name=repo.name,
            owner_login=user.github_login,
            description=repo.description,
            is_private=repo.is_private,
            default_branch=repo.default_branch,
            html_url=repo.html_url,
            clone_url=repo.clone_url,
            language=repo.language,
            stargazers_count=repo.stargazers_count,
        )
        mock_github_service.return_value.fetch_user_repositories.return_value = [
            fake_repo
        ]

        initial_repository_sync_task(user_id=user.pk)

        repo.refresh_from_db()
        assert repo.last_synced_at is not None

    def test_skips_if_user_not_found(self, mock_github_service: MagicMock) -> None:
        """Non-existent user_id should return without error."""
        initial_repository_sync_task(user_id=99999)
        mock_github_service.return_value.fetch_user_repositories.assert_not_called()

    def test_skips_if_no_github_token(self, mock_github_service: MagicMock) -> None:
        """User without a GithubToken should return without error."""
        user = UserFactory(github_token=False)  # Skip token creation
        initial_repository_sync_task(user_id=user.pk)
        mock_github_service.return_value.fetch_user_repositories.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestInstallWebhookTask:
    def test_installs_webhook_and_persists_id(
        self, mock_github_service: MagicMock
    ) -> None:
        repo = RepositoryFactory(webhook_id=None)
        mock_github_service.return_value.install_webhook.return_value = (
            WebhookInstallResult(
                webhook_id=999, ping_url="https://...", events=["pull_request"]
            )
        )

        install_webhook_task(repo_id=repo.pk)

        repo.refresh_from_db()
        assert repo.webhook_id == 999

    def test_skips_if_webhook_already_installed(
        self, mock_github_service: MagicMock
    ) -> None:
        repo = RepositoryFactory(webhook_id=777)

        install_webhook_task(repo_id=repo.pk)

        mock_github_service.return_value.install_webhook.assert_not_called()

    def test_skips_if_repo_not_found(self, mock_github_service: MagicMock) -> None:
        """Non-existent repo_id should return without error."""
        install_webhook_task(repo_id=99999)
        mock_github_service.return_value.install_webhook.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestRemoveWebhookTask:
    def test_removes_webhook_and_clears_id(
        self, mock_github_service: MagicMock
    ) -> None:
        repo = RepositoryFactory(webhook_id=888)
        mock_github_service.return_value.delete_webhook.return_value = None

        remove_webhook_task(repo_id=repo.pk)

        repo.refresh_from_db()
        assert repo.webhook_id is None

    def test_skips_if_repo_not_found(self, mock_github_service: MagicMock) -> None:
        """Non-existent repo_id should return without error."""
        remove_webhook_task(repo_id=99999)
        mock_github_service.return_value.delete_webhook.assert_not_called()
