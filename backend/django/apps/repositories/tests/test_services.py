from __future__ import annotations

import json

import pytest
import responses as rsps
from responses import RequestsMock

from apps.repositories.exceptions import (
    GitHubAuthError,
    GitHubRateLimitError,
    WebhookInstallError,
)
from apps.repositories.services import GitHubService
from apps.repositories.tests.factories import UserFactory


@pytest.fixture
def github_service(db: None) -> GitHubService:
    user = UserFactory()
    return GitHubService(access_token="ghp_test_token_abc123", user=user)


@pytest.fixture
def mock_repo_payload() -> dict[str, object]:
    return {
        "id": 123456789,
        "full_name": "acme/api",
        "name": "api",
        "owner": {"login": "acme"},
        "description": "The ACME API",
        "private": False,
        "default_branch": "main",
        "html_url": "https://github.com/acme/api",
        "clone_url": "https://github.com/acme/api.git",
        "language": "Python",
        "stargazers_count": 42,
        "topics": ["python", "api"],
    }


@pytest.mark.django_db
class TestGitHubServiceFetchRepositories:
    @rsps.activate
    def test_returns_list_of_githubrepodata(
        self,
        github_service: GitHubService,
        mock_repo_payload: dict[str, object],
    ) -> None:
        rsps.add(
            rsps.GET,
            "https://api.github.com/user/repos",
            json=[mock_repo_payload],
            status=200,
        )
        repos = github_service.fetch_user_repositories()
        assert len(repos) == 1
        assert repos[0].github_id == 123456789
        assert repos[0].full_name == "acme/api"
        assert repos[0].language == "Python"

    @rsps.activate
    def test_raises_auth_error_on_401(self, github_service: GitHubService) -> None:
        rsps.add(
            rsps.GET,
            "https://api.github.com/user/repos",
            json={"message": "Bad credentials"},
            status=401,
        )
        with pytest.raises(GitHubAuthError):
            github_service.fetch_user_repositories()

    @rsps.activate
    def test_raises_rate_limit_error_on_403(
        self, github_service: GitHubService
    ) -> None:
        rsps.add(
            rsps.GET,
            "https://api.github.com/user/repos",
            json={"message": "rate limit exceeded"},
            status=403,
            headers={"X-RateLimit-Reset": "9999999999"},
        )
        with pytest.raises(GitHubRateLimitError) as exc_info:
            github_service.fetch_user_repositories()
        assert exc_info.value.reset_at == 9999999999

    @rsps.activate
    def test_paginates_all_pages(
        self,
        github_service: GitHubService,
        mock_repo_payload: dict[str, object],
    ) -> None:
        """Service must follow Link: rel="next" pagination headers."""
        rsps.add(
            rsps.GET,
            "https://api.github.com/user/repos",
            json=[mock_repo_payload],
            status=200,
            headers={"Link": '<https://api.github.com/user/repos?page=2>; rel="next"'},
        )
        second_repo = {**mock_repo_payload, "id": 999999999, "full_name": "acme/web"}
        rsps.add(
            rsps.GET,
            "https://api.github.com/user/repos",
            json=[second_repo],
            status=200,
        )
        repos = github_service.fetch_user_repositories()
        assert len(repos) == 2


@pytest.mark.django_db
class TestGitHubServiceInstallWebhook:
    @rsps.activate
    def test_install_webhook_returns_result(
        self, github_service: GitHubService
    ) -> None:
        rsps.add(
            rsps.POST,
            "https://api.github.com/repos/acme/api/hooks",
            json={
                "id": 789,
                "ping_url": "https://api.github.com/repos/acme/api/hooks/789/pings",
                "events": ["pull_request", "push"],
            },
            status=201,
        )
        result = github_service.install_webhook("acme/api")
        assert result.webhook_id == 789
        assert "pull_request" in result.events

    @rsps.activate
    def test_install_webhook_raises_on_422(self, github_service: GitHubService) -> None:
        rsps.add(
            rsps.POST,
            "https://api.github.com/repos/acme/api/hooks",
            json={"message": "Validation Failed"},
            status=422,
        )
        with pytest.raises(WebhookInstallError):
            github_service.install_webhook("acme/api")

    @rsps.activate
    def test_delete_webhook_calls_correct_endpoint(
        self, github_service: GitHubService
    ) -> None:
        rsps.add(
            rsps.DELETE,
            "https://api.github.com/repos/acme/api/hooks/789",
            status=204,
        )
        # Should not raise
        github_service.delete_webhook("acme/api", webhook_id=789)

    @rsps.activate
    def test_get_pull_request_diff_returns_string(
        self, github_service: GitHubService
    ) -> None:
        diff_content = "diff --git a/foo.py b/foo.py\n+print('hello')"
        rsps.add(
            rsps.GET,
            "https://api.github.com/repos/acme/api/pulls/42",
            body=diff_content,
            status=200,
            content_type="application/vnd.github.v3.diff",
        )
        diff = github_service.get_pull_request_diff("acme/api", pr_number=42)
        assert diff == diff_content
