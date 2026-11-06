"""
Developer feedback on DevMind's review comments.

What counts as accepted or rejected (also in docs/feedback-learning.md):

- reaction: when the PR closes, the 👍 (+1) and 👎 (-1) reactions on each
  inline comment DevMind posted are counted. More 👍 than 👎 is accepted,
  more 👎 than 👍 is rejected. A tie, including no reactions, is no signal
  and removes an earlier reaction verdict. Other reactions are ignored.
- reply: a reply to a DevMind comment whose text starts with one of
  ACCEPTED_REPLY_PHRASES or REJECTED_REPLY_PHRASES (case-insensitive, quoted
  lines ignored). Other replies are no signal. A later reply with a verdict
  replaces an earlier one. Replies from bot accounts are ignored.
- resolved: resolving the comment's thread is accepted. Unresolving it
  removes that verdict.

A comment has at most one row per source. When sources disagree, the
reaction wins over the reply, and the reply over the resolved thread
(CommentFeedback.SOURCE_PRECEDENCE). Whenever that effective verdict changes,
it is sent to FastAPI, which embeds the comment with its code hunk for later
reviews of the same repository.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from django.conf import settings
from django.db import transaction

from apps.reviews.models import CommentFeedback, ReviewComment

logger = logging.getLogger(__name__)

ACCEPTED = "accepted"
REJECTED = "rejected"

ACCEPTED_REPLY_PHRASES = (
    "fixed",
    "done",
    "good catch",
    "nice catch",
    "addressed",
    "agreed",
)
REJECTED_REPLY_PHRASES = (
    "false positive",
    "not an issue",
    "not a bug",
    "won't fix",
    "wont fix",
    "wontfix",
    "disagree",
)

# Hunks sent to FastAPI are cut to this many characters.
MAX_HUNK_CHARS = 4000

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def classify_reactions(plus_one: int, minus_one: int) -> str | None:
    """Accepted, rejected or None from 👍 and 👎 counts."""
    if plus_one > minus_one:
        return ACCEPTED
    if minus_one > plus_one:
        return REJECTED
    return None


def _starts_with_phrase(text: str, phrase: str) -> bool:
    if not text.startswith(phrase):
        return False
    rest = text[len(phrase) :]
    # "fixed." and "done!" count; "doneness" doesn't.
    return not rest or not rest[0].isalnum()


def classify_reply(body: str) -> str | None:
    """Accepted, rejected or None from a reply's text."""
    lines = [line for line in body.splitlines() if not line.lstrip().startswith(">")]
    text = " ".join(" ".join(lines).split()).lower().replace("’", "'")
    for phrase in REJECTED_REPLY_PHRASES:
        if _starts_with_phrase(text, phrase):
            return REJECTED
    for phrase in ACCEPTED_REPLY_PHRASES:
        if _starts_with_phrase(text, phrase):
            return ACCEPTED
    return None


def effective_signal(comment: ReviewComment) -> str | None:
    """The comment's current verdict, read from the database."""
    row = CommentFeedback.effective(CommentFeedback.objects.filter(comment=comment))
    return row.signal if row else None


def record_feedback(comment: ReviewComment, source: str, signal: str | None) -> bool:
    """
    Store (or with signal=None remove) the comment's verdict from ``source``.

    Returns True when the comment's effective verdict changed; the change is
    then sent to FastAPI after the transaction commits.
    """
    with transaction.atomic():
        # Lock the comment so concurrent events for it apply one at a time.
        ReviewComment.objects.select_for_update().filter(pk=comment.pk).first()
        before = effective_signal(comment)
        if signal is None:
            CommentFeedback.objects.filter(comment=comment, source=source).delete()
        else:
            CommentFeedback.objects.update_or_create(
                comment=comment, source=source, defaults={"signal": signal}
            )
        after = effective_signal(comment)
        changed = before != after
        if changed:
            from apps.reviews.tasks import sync_comment_feedback_task

            comment_pk = comment.pk
            transaction.on_commit(lambda: sync_comment_feedback_task.delay(comment_pk))

    logger.info(
        "feedback.recorded comment_id=%d source=%s signal=%s effective=%s",
        comment.pk,
        source,
        signal,
        after,
    )
    return changed


def _find_comment(repo_github_id: int, github_comment_ids: list[int]):
    if not github_comment_ids:
        return None
    return (
        ReviewComment.objects.filter(
            github_comment_id__in=github_comment_ids,
            review__repository__github_id=repo_github_id,
            review__repository__is_active=True,
        )
        .order_by("github_comment_id")
        .first()
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _repo_github_id(payload: dict[str, Any]) -> int | None:
    repo = payload.get("repository")
    return _int_or_none(repo.get("id")) if isinstance(repo, dict) else None


def handle_review_thread_event(payload: dict[str, Any]) -> bool:
    """
    pull_request_review_thread: resolved → accepted, unresolved → removed.

    Returns True when a DevMind comment's feedback was recorded.
    """
    action = payload.get("action")
    if action not in ("resolved", "unresolved"):
        return False
    repo_github_id = _repo_github_id(payload)
    thread = payload.get("thread")
    if repo_github_id is None or not isinstance(thread, dict):
        return False
    thread_comments = thread.get("comments")
    if not isinstance(thread_comments, list):
        return False
    ids = [
        comment_id
        for comment_id in (
            _int_or_none(item.get("id"))
            for item in thread_comments
            if isinstance(item, dict)
        )
        if comment_id is not None
    ]
    comment = _find_comment(repo_github_id, ids)
    if comment is None:
        return False
    record_feedback(comment, "resolved", ACCEPTED if action == "resolved" else None)
    return True


def handle_review_comment_event(payload: dict[str, Any]) -> bool:
    """
    pull_request_review_comment: a created or edited reply to a DevMind
    comment whose text is a verdict (classify_reply).

    Returns True when a DevMind comment's feedback was recorded.
    """
    if payload.get("action") not in ("created", "edited"):
        return False
    repo_github_id = _repo_github_id(payload)
    reply = payload.get("comment")
    if repo_github_id is None or not isinstance(reply, dict):
        return False
    parent_id = _int_or_none(reply.get("in_reply_to_id"))
    if parent_id is None:
        return False
    user = reply.get("user")
    if isinstance(user, dict) and user.get("type") == "Bot":
        return False
    signal = classify_reply(str(reply.get("body") or ""))
    if signal is None:
        return False
    comment = _find_comment(repo_github_id, [parent_id])
    if comment is None:
        return False
    record_feedback(comment, "reply", signal)
    return True


def fetch_reaction_feedback(repo_id: int, pr_number: int) -> int:
    """
    Count 👍/👎 on DevMind's inline comments of a closed PR and record them.

    One paginated GitHub call per PR (the comment list includes reaction
    counts), made with the repository owner's token. Comments missing on
    GitHub (deleted) keep any earlier verdict. Returns how many comments
    were checked. Raises GitHubRateLimitError when the quota is low.
    """
    from apps.repositories.models import Repository
    from apps.repositories.services import GitHubService

    comments = list(
        ReviewComment.objects.filter(
            review__repository_id=repo_id,
            review__pr_number=pr_number,
            github_comment_id__isnull=False,
        )
    )
    if not comments:
        return 0

    repo = Repository.objects.select_related("owner").get(pk=repo_id)
    service = GitHubService(
        access_token=repo.owner.github_token.access_token,
        user=repo.owner,
    )
    items = service.list_pull_request_review_comments(repo.full_name, pr_number)
    by_id = {
        _int_or_none(item.get("id")): item for item in items if isinstance(item, dict)
    }

    checked = 0
    for comment in comments:
        item = by_id.get(comment.github_comment_id)
        if item is None:
            continue
        reactions = item.get("reactions") or {}
        signal = classify_reactions(
            _int_or_none(reactions.get("+1")) or 0,
            _int_or_none(reactions.get("-1")) or 0,
        )
        record_feedback(comment, "reaction", signal)
        checked += 1
    return checked


def extract_hunk(diff_text: str, file_path: str, line_number: int) -> str:
    """
    The hunk of ``file_path`` in a unified diff whose new-side range holds
    ``line_number``, header included. "" when there is none.
    """
    in_file = False
    hunk: list[str] = []
    hunk_matches = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if hunk_matches:
                break
            in_file = False
            hunk, hunk_matches = [], False
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            in_file = target.removeprefix("b/") == file_path
            continue
        if not in_file:
            continue
        header = _HUNK_HEADER.match(line)
        if header:
            if hunk_matches:
                break
            start = int(header.group(1))
            length = int(header.group(2)) if header.group(2) is not None else 1
            hunk = [line]
            hunk_matches = start <= line_number < start + max(length, 1)
            continue
        if hunk:
            hunk.append(line)

    if not hunk_matches:
        return ""
    return "\n".join(hunk)[:MAX_HUNK_CHARS]


def feedback_payload(comment: ReviewComment) -> dict[str, Any]:
    """The body sent to FastAPI's POST /feedback/upsert for one comment."""
    run = getattr(comment.review, "run", None)
    diff_text = run.diff_text if run else ""
    return {
        "comment_id": comment.pk,
        "repo_full_name": comment.review.repository.full_name,
        "signal": effective_signal(comment),
        "file_path": comment.file_path,
        "line_number": comment.line_number,
        "category": comment.category,
        "severity": comment.severity,
        "body": comment.body,
        "code_hunk": extract_hunk(diff_text, comment.file_path, comment.line_number),
    }


class FeedbackSyncError(Exception):
    """FastAPI didn't store the feedback; the Celery task retries."""


def sync_comment_feedback(comment_id: int) -> None:
    """
    Send a comment's effective verdict to FastAPI. A null signal makes
    FastAPI delete the comment's stored example.
    """
    comment = (
        ReviewComment.objects.select_related("review__repository", "review__run")
        .filter(pk=comment_id)
        .first()
    )
    if comment is None:
        return

    secret = getattr(settings, "FASTAPI_INTERNAL_SECRET", "")
    if not secret:
        raise FeedbackSyncError("FASTAPI_INTERNAL_SECRET is not set.")
    base_url = getattr(settings, "FASTAPI_BASE_URL", "http://fastapi:8001").rstrip("/")

    try:
        response = httpx.post(
            f"{base_url}/feedback/upsert",
            json=feedback_payload(comment),
            headers={"X-Internal-Secret": secret},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise FeedbackSyncError(f"FastAPI unreachable: {exc}") from exc
    if response.status_code != 200:
        raise FeedbackSyncError(
            f"FastAPI /feedback/upsert returned {response.status_code}"
        )
