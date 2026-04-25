"""
Domain-specific type aliases and dataclasses for the repositories app.
Centralising types here prevents circular imports between services and models.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GitHubRepoData:
    """
    Immutable snapshot of a GitHub repository's metadata as returned by the API.
    Frozen so it can be safely passed between service → model layers without mutation.
    """

    github_id: int
    full_name: str
    name: str
    owner_login: str
    description: str | None
    is_private: bool
    default_branch: str
    html_url: str
    clone_url: str
    language: str | None
    stargazers_count: int
    topics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WebhookInstallResult:
    """Returned by GitHubService.install_webhook()."""

    webhook_id: int
    ping_url: str
    events: list[str]


# Type alias for GitHub API response payloads (raw dict before parsing)
type GitHubPayload = dict[str, object]
type RepoFullName = str  # e.g. "acme/api"
