"""
GitHub API service layer.

Design rules enforced here:
1. No Django ORM access — services are pure Python, composable by tasks and views.
2. All HTTP via requests (sync) — easy to swap to async in FastAPI service.
3. All responses parsed into typed dataclasses before returning.
4. Network errors retried with tenacity before raising domain exceptions.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import requests
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from apps.repositories.exceptions import (
    GitHubAuthError,
    GitHubRateLimitError,
    GitHubServiceError,
    WebhookInstallError,
)
from apps.repositories.types import GitHubRepoData, WebhookInstallResult

if TYPE_CHECKING:
    from django.contrib.auth import get_user_model

    User = get_user_model()

log: structlog.BoundLogger = structlog.get_logger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_WEBHOOK_EVENTS = ["pull_request", "push"]
GITHUB_WEBHOOK_URL_TEMPLATE = "{base}/api/v1/webhooks/github/"

# Retry on transient server errors only — never retry auth failures
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


def _should_retry(exc: BaseException) -> bool:
    return isinstance(exc, GitHubServiceError) and not isinstance(
        exc, GitHubAuthError | GitHubRateLimitError
    )


class GitHubService:
    """
    Wraps GitHub REST API v3 interactions.

    Usage:
        service = GitHubService(access_token=user.githubtoken.access_token, user=user)
        repos = service.fetch_user_repositories()
    """

    def __init__(self, access_token: str, user: User) -> None:
        self._access_token = access_token
        self._user = user
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def _handle_response_errors(self, response: requests.Response) -> None:
        """Translate GitHub HTTP errors into domain exceptions."""
        if (
            response.status_code == 200
            or response.status_code == 201
            or response.status_code == 204
        ):
            return
        if response.status_code == 401:
            raise GitHubAuthError("GitHub token is invalid or expired.")
        if response.status_code == 403:
            reset_at_raw = response.headers.get("X-RateLimit-Reset", "0")
            raise GitHubRateLimitError(reset_at=int(reset_at_raw))
        if response.status_code in _RETRYABLE_STATUS:
            raise GitHubServiceError(
                f"GitHub API transient error: {response.status_code}"
            )
        raise GitHubServiceError(
            f"GitHub API error {response.status_code}: {response.text[:200]}"
        )

    @staticmethod
    def _parse_repo(data: dict[str, Any]) -> GitHubRepoData:
        return GitHubRepoData(
            github_id=int(data["id"]),
            full_name=str(data["full_name"]),
            name=str(data["name"]),
            owner_login=str(data["owner"]["login"]),
            description=data.get("description") or None,
            is_private=bool(data.get("private", False)),
            default_branch=str(data.get("default_branch", "main")),
            html_url=str(data["html_url"]),
            clone_url=str(data["clone_url"]),
            language=data.get("language") or None,
            stargazers_count=int(data.get("stargazers_count", 0)),
            topics=list(data.get("topics", [])),
        )

    @retry(
        retry=retry_if_exception_type(GitHubServiceError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def fetch_user_repositories(self) -> list[GitHubRepoData]:
        """
        Fetches all repositories accessible by the authenticated user.
        Follows GitHub pagination automatically.
        """
        repos: list[GitHubRepoData] = []
        url: str | None = "/user/repos"
        params: dict[str, str | int] = {
            "per_page": 100,
            "sort": "pushed",
            "type": "all",
        }

        while url is not None:
            full_url = GITHUB_API_BASE + url if url.startswith("/") else url
            response = self._session.get(full_url, params=params, timeout=30.0)
            self._handle_response_errors(response)
            batch: list[dict[str, Any]] = response.json()
            repos.extend(self._parse_repo(r) for r in batch)

            # Follow GitHub's Link header for pagination
            link_header = response.headers.get("Link", "")
            next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            if next_match:
                # Next URL is absolute — use directly
                url = next_match.group(1)
                params = {}  # URL already contains params
            else:
                url = None

        log.info(
            "github.repos.fetched",
            user_id=self._user.pk,
            count=len(repos),
        )
        return repos

    @retry(
        retry=retry_if_exception_type(GitHubServiceError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def install_webhook(
        self,
        repo_full_name: str,
        callback_base_url: str = "",
    ) -> WebhookInstallResult:
        """
        Installs a GitHub webhook on the given repository.
        The callback URL must be publicly reachable by GitHub.
        """
        from django.conf import settings

        webhook_url = (
            callback_base_url
            or getattr(settings, "DEVMIND_PUBLIC_URL", "http://localhost:8000")
        ) + "/api/v1/webhooks/github/"

        payload = {
            "name": "web",
            "active": True,
            "events": GITHUB_WEBHOOK_EVENTS,
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": settings.GITHUB_WEBHOOK_SECRET,
                "insecure_ssl": "0",
            },
        }

        response = self._session.post(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/hooks",
            json=payload,
            timeout=30.0,
        )

        if response.status_code == 422:
            raise WebhookInstallError(
                f"Webhook install failed for {repo_full_name}: {response.text[:200]}"
            )
        self._handle_response_errors(response)
        data: dict[str, Any] = response.json()

        log.info(
            "github.webhook.installed",
            repo=repo_full_name,
            webhook_id=data["id"],
        )
        return WebhookInstallResult(
            webhook_id=int(data["id"]),
            ping_url=str(data["ping_url"]),
            events=list(data.get("events", [])),
        )

    def delete_webhook(self, repo_full_name: str, webhook_id: int) -> None:
        """Removes a GitHub webhook. Idempotent — 404 is silently ignored."""
        response = self._session.delete(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/hooks/{webhook_id}", timeout=30.0
        )
        if response.status_code == 404:
            log.warning(
                "github.webhook.not_found_on_delete",
                repo=repo_full_name,
                webhook_id=webhook_id,
            )
            return
        self._handle_response_errors(response)
        log.info("github.webhook.deleted", repo=repo_full_name, webhook_id=webhook_id)

    def get_pull_request_diff(self, repo_full_name: str, pr_number: int) -> str:
        """Fetches the unified diff for a pull request as a plain string."""
        response = self._session.get(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
            timeout=30.0,
        )
        self._handle_response_errors(response)
        return response.text

    def __del__(self) -> None:
        self._session.close()
