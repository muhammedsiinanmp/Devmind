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
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

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
    GitHubNotFoundError,
    GitHubPermissionError,
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
GITHUB_WEBHOOK_EVENTS = [
    "pull_request",
    "push",
    # Replies to DevMind's comments and resolved threads (feedback learning).
    "pull_request_review_comment",
    "pull_request_review_thread",
]
GITHUB_WEBHOOK_URL_TEMPLATE = "{base}/api/v1/webhooks/github/"

# Retry on transient server errors only — never retry auth failures
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})

# Paginated reads stop before the next page when fewer requests than this are
# left in the token's hourly quota, so feedback polling never uses up the
# quota that posting reviews needs.
RATE_LIMIT_FLOOR = 100


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
        if response.status_code in (403, 429):
            # Secondary rate limits send Retry-After (seconds) instead.
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                raise GitHubRateLimitError(reset_at=int(time.time()) + int(retry_after))
            # A 403 is a rate limit only when the quota is used up; otherwise
            # the token lacks access, and waiting won't help.
            remaining = response.headers.get("X-RateLimit-Remaining")
            if response.status_code == 429 or remaining == "0":
                reset_at_raw = response.headers.get("X-RateLimit-Reset", "0")
                raise GitHubRateLimitError(
                    reset_at=int(reset_at_raw) if reset_at_raw.isdigit() else 0
                )
            raise GitHubPermissionError("GitHub denied access (403).")
        if response.status_code == 404:
            raise GitHubNotFoundError("GitHub resource not found (404).")
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

    def get_pull_request(
        self, repo_full_name: str, pr_number: int
    ) -> dict[str, object]:
        """Fetches pull request metadata from GitHub API."""
        response = self._session.get(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}",
            headers={"Accept": "application/vnd.github+json"},
            timeout=30.0,
        )
        self._handle_response_errors(response)
        data: dict[str, object] = response.json()
        return {
            "title": str(data.get("title", "")),
            "head_sha": str(data.get("head", {}).get("sha", "")),
            "base_sha": str(data.get("base", {}).get("sha", "")),
            "diff_url": str(data.get("diff_url", "")),
        }

    def get_pull_request_diff(self, repo_full_name: str, pr_number: int) -> str:
        """Fetches the unified diff for a pull request as a plain string."""
        response = self._session.get(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
            timeout=30.0,
        )
        self._handle_response_errors(response)
        return response.text

    def _budgeted_get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> requests.Response:
        """
        GET that stops before the request when an earlier response of this
        service showed fewer than RATE_LIMIT_FLOOR requests left in the
        token's hourly quota (raises GitHubRateLimitError with the reset).
        Used by the feedback reads, so they never use up the quota that
        posting reviews needs.
        """
        remaining = getattr(self, "_quota_remaining", None)
        if remaining is not None and remaining < RATE_LIMIT_FLOOR:
            raise GitHubRateLimitError(reset_at=getattr(self, "_quota_reset", 0))
        response = self._session.get(url, params=params or {}, timeout=30.0)
        remaining_raw = response.headers.get("X-RateLimit-Remaining", "")
        if remaining_raw.isdigit():
            self._quota_remaining = int(remaining_raw)
            reset_raw = response.headers.get("X-RateLimit-Reset", "")
            self._quota_reset = int(reset_raw) if reset_raw.isdigit() else 0
        self._handle_response_errors(response)
        return response

    def _get_all_pages(self, url: str) -> list[dict[str, Any]]:
        """
        GETs every page of a GitHub list endpoint, 100 items per page, within
        the quota floor (_budgeted_get). Next-page links are only followed to
        https://api.github.com, so the token is never sent anywhere else.
        """
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        params: dict[str, int] = {"per_page": 100}
        while next_url is not None:
            response = self._budgeted_get(next_url, params)
            items.extend(response.json())

            link_header = response.headers.get("Link", "")
            next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
            if not next_match:
                break
            next_url = next_match.group(1)
            parsed = urlparse(next_url)
            if parsed.scheme != "https" or parsed.netloc != "api.github.com":
                log.warning("github.pagination.foreign_link", host=parsed.netloc)
                break
            params = {}  # The next URL already carries the query string.
        return items

    def get_collaborator_permission(self, repo_full_name: str, login: str) -> str:
        """
        The user's permission on the repository as GitHub's ``permission``
        field gives it: "admin", "write", "read" or "none". GitHub maps
        maintain to write, triage to read, and a custom role to its base
        role there (``role_name`` can be a custom name, so it isn't used).
        A user GitHub doesn't know (404) is "none".
        """
        try:
            response = self._budgeted_get(
                f"{GITHUB_API_BASE}/repos/{repo_full_name}/collaborators/"
                f"{quote(login, safe='')}/permission"
            )
        except GitHubNotFoundError:
            return "none"
        return str(response.json().get("permission") or "none")

    def list_review_comment_reactions(
        self, repo_full_name: str, comment_id: int
    ) -> list[dict[str, Any]]:
        """Every reaction on one pull request review comment, with its user."""
        return self._get_all_pages(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/comments/"
            f"{comment_id}/reactions"
        )

    def get_pull_request_author(self, repo_full_name: str, pr_number: int) -> str:
        """Login of the user who opened the pull request."""
        response = self._budgeted_get(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}"
        )
        user = response.json().get("user") or {}
        return str(user.get("login") or "")

    def list_pull_request_review_comments(
        self, repo_full_name: str, pr_number: int
    ) -> list[dict[str, Any]]:
        """
        All inline review comments on a pull request, as GitHub returns them.

        Each item has a "reactions" rollup ({"+1": n, "-1": n, ...}), so one
        paginated call covers the reactions on every comment of the PR.
        """
        return self._get_all_pages(
            f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}/comments"
        )

    def __del__(self) -> None:
        if hasattr(self, "_session") and self._session:
            self._session.close()
