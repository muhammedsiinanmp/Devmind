"""
Domain exceptions for the repositories app.
Raising typed exceptions from the service layer lets views return
the correct HTTP status without knowing about GitHub API internals.
"""


class GitHubServiceError(Exception):
    """Base exception for all GitHub API failures."""


class GitHubAuthError(GitHubServiceError):
    """Raised when the user's GitHub token is invalid or expired."""


class GitHubRateLimitError(GitHubServiceError):
    """Raised when we hit GitHub's rate limit."""

    def __init__(self, reset_at: int) -> None:
        self.reset_at = reset_at
        super().__init__(f"GitHub rate limit exceeded. Resets at {reset_at}.")


class GitHubPermissionError(GitHubServiceError):
    """A 403 that isn't a rate limit: the token may not do this. Not retried."""


class GitHubNotFoundError(GitHubServiceError):
    """A 404: the resource doesn't exist or the token can't see it. Not retried."""


# Errors that a retry can't fix.
PERMANENT_GITHUB_ERRORS = (GitHubAuthError, GitHubPermissionError, GitHubNotFoundError)


class WebhookVerificationError(Exception):
    """
    Raised when a webhook's HMAC-SHA256 signature does not match.
    Must result in HTTP 403 — never 400, as a 400 reveals structural info.
    """


class WebhookInstallError(GitHubServiceError):
    """Raised when webhook installation on GitHub fails."""


class RepositoryNotFoundError(Exception):
    """Raised when a repository record does not exist for a given user."""
