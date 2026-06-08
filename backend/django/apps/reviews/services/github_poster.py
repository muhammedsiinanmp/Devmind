"""
GitHub Comment Poster - Post AI review comments to GitHub PRs.

Uses GitHub Create Pull Request Review API to post comments in batches.
"""

import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
MAX_COMMENTS_PER_REVIEW = 50


def group_by_file(comments: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Group comments by file path.

    Args:
        comments: List of comment dicts

    Returns:
        Dict mapping file_path -> list of comments
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for comment in comments:
        file_path = comment.get("file_path", "")
        if file_path not in grouped:
            grouped[file_path] = []
        grouped[file_path].append(comment)
    return grouped


def format_suggestion_block(severity: str, body: str, suggested_fix: str) -> str:
    """
    Format a comment with suggested fix as GitHub suggestion block.

    Args:
        severity: critical, error, warning, info
        body: Original comment body
        suggested_fix: The suggested code fix

    Returns:
        Formatted markdown with suggestion block
    """
    emoji_map = {
        "critical": "🔴",
        "error": "🟠",
        "warning": "🟡",
        "info": "🔵",
    }
    emoji = emoji_map.get(severity, "🔵")
    return f"{emoji} {body}\n\n```suggestion\n{suggested_fix}\n```"


@dataclass
class CommentPayload:
    """Formatted comment for GitHub API."""

    path: str
    line: int
    body: str


class GitHubPoster:
    """
    Posts review comments to GitHub Pull Requests.

    Groups comments by file and uses GitHub's Create Review API
    to avoid notification spam.
    """

    def __init__(self, access_token: str):
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def post_review_comments(
        self,
        repo_full_name: str,
        pr_number: int,
        head_sha: str,
        comments: list[dict[str, Any]],
        summary: str,
    ) -> list[int]:
        """
        Post comments to a PR review.

        Args:
            repo_full_name: "owner/repo" format
            pr_number: PR number
            head_sha: Commit SHA of the PR head
            comments: List of ReviewComment dicts
            summary: Summary text for the review body

        Returns:
            List of HTTP status codes from API calls
        """
        if not comments:
            logger.info(
                "github_poster.no_comments repo=%s pr=%d", repo_full_name, pr_number
            )
            return []

        # Split: inline comments need a valid line number (> 0).
        # Comments with line_number <= 0 (LLM returned 0 or omitted it) would
        # cause GitHub to return 422 for the entire batch, silently dropping all
        # comments. Fold those into the review body summary instead.
        inline = [c for c in comments if (c.get("line_number") or 0) > 0]
        body_only = [c for c in comments if (c.get("line_number") or 0) <= 0]

        if body_only:
            extra_lines = [summary] if summary else []
            for c in body_only:
                emoji = self._severity_emoji(c.get("severity", "info"))
                file_ref = c.get("file_path", "")
                extra_lines.append(f"\n**{file_ref}** — {emoji} {c.get('body', '')}")
            summary = "\n".join(extra_lines)

        if not inline:
            # No inline comments — post a body-only review to deliver the summary.
            if summary:
                status = self._post_review(
                    repo_full_name=repo_full_name,
                    pr_number=pr_number,
                    head_sha=head_sha,
                    comments=[],
                    summary=summary,
                )
                return [status]
            return []

        grouped = self.group_by_file(inline)
        status_codes = []

        batches = self._create_batches(grouped)
        for batch in batches:
            status = self._post_review(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                head_sha=head_sha,
                comments=batch,
                summary=summary if batch == batches[-1] else "",
            )
            status_codes.append(status)

        logger.info(
            "github_poster.posted repo=%s pr=%d comments=%d calls=%d",
            repo_full_name,
            pr_number,
            len(comments),
            len(status_codes),
        )
        return status_codes

    def group_by_file(
        self, comments: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Group comments by file path.

        Args:
            comments: List of comment dicts

        Returns:
            Dict mapping file_path -> list of comments
        """
        grouped: dict[str, list[dict[str, Any]]] = {}
        for comment in comments:
            file_path = comment.get("file_path", "")
            if file_path not in grouped:
                grouped[file_path] = []
            grouped[file_path].append(comment)
        return grouped

    def _create_batches(
        self, grouped: dict[str, list[dict[str, Any]]]
    ) -> list[list[CommentPayload]]:
        """Split comments into batches of MAX_COMMENTS_PER_REVIEW."""
        batches: list[list[CommentPayload]] = []
        current_batch: list[CommentPayload] = []

        for file_path, file_comments in grouped.items():
            for comment in file_comments:
                payload = self._format_comment(comment)
                current_batch.append(payload)

                if len(current_batch) >= MAX_COMMENTS_PER_REVIEW:
                    batches.append(current_batch)
                    current_batch = []

        if current_batch:
            batches.append(current_batch)

        return batches

    def _format_comment(self, comment: dict[str, Any]) -> CommentPayload:
        """Format a single comment for GitHub API."""
        severity = comment.get("severity", "info")
        body = comment.get("body", "")

        if comment.get("suggested_fix"):
            body = self.format_suggestion_block(
                severity=severity,
                body=body,
                suggested_fix=comment["suggested_fix"],
            )
        else:
            body = f"{self._severity_emoji(severity)} {body}"

        return CommentPayload(
            path=comment.get("file_path", ""),
            line=comment.get("line_number", 1),
            body=body,
        )

    def format_suggestion_block(
        self, severity: str, body: str, suggested_fix: str
    ) -> str:
        """
        Format a comment with suggested fix as GitHub suggestion block.

        Args:
            severity: critical, error, warning, info
            body: Original comment body
            suggested_fix: The suggested code fix

        Returns:
            Formatted markdown with suggestion block
        """
        emoji = self._severity_emoji(severity)
        return f"{emoji} {body}\n\n```suggestion\n{suggested_fix}\n```"

    def _severity_emoji(self, severity: str) -> str:
        """Map severity to emoji prefix."""
        mapping = {
            "critical": "🔴",
            "error": "🟠",
            "warning": "🟡",
            "info": "🔵",
        }
        return mapping.get(severity, "🔵")

    def _post_review(
        self,
        repo_full_name: str,
        pr_number: int,
        head_sha: str,
        comments: list[CommentPayload],
        summary: str,
    ) -> int:
        """Post a review with comments to GitHub API."""
        payload = {
            "commit_id": head_sha,
            "event": "COMMENT",
            "body": summary,
            "comments": [
                {
                    "path": c.path,
                    "line": c.line,
                    "side": "RIGHT",
                    "body": c.body,
                }
                for c in comments
            ],
        }

        url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}/reviews"
        response = self._session.post(url, json=payload, timeout=30.0)

        if response.status_code == 422 and payload["comments"]:
            # Inline comments have invalid line numbers (LLM hallucinated lines
            # outside the diff). Retry as a body-only review so comments aren't lost.
            logger.warning(
                "github_poster.inline_failed_retrying_body_only repo=%s pr=%d",
                repo_full_name,
                pr_number,
            )
            fallback_lines = [payload["body"]] if payload["body"] else []
            for c in comments:
                fallback_lines.append(f"**`{c.path}` line {c.line}** — {c.body}")
            fallback_payload = {
                "commit_id": head_sha,
                "event": "COMMENT",
                "body": "\n\n".join(fallback_lines),
                "comments": [],
            }
            response = self._session.post(url, json=fallback_payload, timeout=30.0)

        if response.status_code not in (200, 201):
            logger.error(
                "github_poster.api_error repo=%s pr=%d status=%d",
                repo_full_name,
                pr_number,
                response.status_code,
            )

        return response.status_code

    def __del__(self) -> None:
        self._session.close()


def post_github_comments(review_id: int) -> list[int]:
    """
    Post comments for a completed review to GitHub.

    Args:
        review_id: Review instance ID

    Returns:
        List of HTTP status codes from API calls
    """
    from apps.reviews.models import Review

    review = Review.objects.select_related("repository", "repository__owner").get(
        pk=review_id
    )

    if review.status != "completed":
        logger.warning("github_poster.skip_not_completed review_id=%d", review_id)
        return []

    comments = list(
        review.comments.values(
            "file_path", "line_number", "category", "severity", "body", "suggested_fix"
        )
    )

    if not comments:
        logger.info("github_poster.no_review_comments review_id=%d", review_id)
        return []

    access_token = review.repository.owner.github_token.access_token
    poster = GitHubPoster(access_token)

    return poster.post_review_comments(
        repo_full_name=review.repository.full_name,
        pr_number=review.pr_number,
        head_sha=review.head_sha,
        comments=comments,
        summary=review.summary or "AI Code Review Complete",
    )
