"""
Developer feedback on DevMind's review comments.

What counts as accepted or rejected (also in docs/feedback-learning.md):

Only trusted users' signals count (TrustChecker): the DevMind user who
connected the repository, the repository owner, and users with write or
admin permission. The pull request's own author never counts on it.

- reaction: when the PR closes, trusted users' 👍 (+1) and 👎 (-1) on each
  inline comment DevMind posted are counted. More 👍 than 👎 is accepted,
  more 👎 than 👍 is rejected. A tie, including no reactions, is no signal
  and removes an earlier reaction verdict. Other reactions are ignored.
- reply: a trusted user's reply to a DevMind comment whose text starts with
  one of ACCEPTED_REPLY_PHRASES or REJECTED_REPLY_PHRASES (case-insensitive,
  quoted lines ignored). Other replies are no signal. A later reply with a
  verdict replaces an earlier one. Deleting the reply that gave the
  verdict, or editing it so it has none, removes the verdict.
- resolved: a trusted user resolving the comment's thread is accepted;
  a trusted user unresolving it removes that verdict.

A comment has at most one row per source. When sources disagree, the
reaction wins over the reply, and the reply over the resolved thread
(CommentFeedback.SOURCE_PRECEDENCE). Whenever that effective verdict changes,
it is sent to FastAPI, which embeds the comment with its code hunk for later
reviews of the same repository.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.reviews.models import (
    CommentFeedback,
    DeletedFeedbackReply,
    ReviewComment,
)

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

# author_association values that may belong to a trusted user. OWNER is
# trusted outright; MEMBER and COLLABORATOR still need write permission.
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
# GitHub's permission field: maintain is reported as write, triage as read.
WRITE_PERMISSIONS = frozenset({"admin", "write"})

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


def record_feedback(
    comment: ReviewComment,
    source: str,
    signal: str | None,
    source_github_id: int | None = None,
    event_at: datetime | None = None,
) -> bool:
    """
    Store (or with signal=None clear) the comment's verdict from ``source``.
    ``source_github_id`` is the reply that gave a reply verdict.

    ``event_at`` is when the event happened (default: now). An event
    older than the one that last set this source is ignored, so a
    retried or redelivered event can't undo a newer one. Clearing keeps
    the row with no signal as the marker that holds that time.

    Returns True when the comment's effective verdict changed; the change is
    then sent to FastAPI after the transaction commits.
    """
    with transaction.atomic():
        # Lock the comment so concurrent events for it apply one at a time.
        ReviewComment.objects.select_for_update().filter(pk=comment.pk).first()
        event_at = event_at or timezone.now()
        row = CommentFeedback.objects.filter(comment=comment, source=source).first()
        if row is not None and row.event_at and event_at < row.event_at:
            logger.info(
                "feedback.stale_event comment_id=%d source=%s", comment.pk, source
            )
            return False
        before = effective_signal(comment)
        CommentFeedback.objects.update_or_create(
            comment=comment,
            source=source,
            defaults={
                "signal": signal,
                "source_github_id": source_github_id,
                "event_at": event_at,
            },
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


def _login(user: Any) -> str:
    return str(user.get("login") or "") if isinstance(user, dict) else ""


def _user_type(user: Any) -> str:
    return str(user.get("type") or "") if isinstance(user, dict) else ""


def _user_id(user: Any) -> int | None:
    return _int_or_none(user.get("id")) if isinstance(user, dict) else None


def _pr_fields(payload: dict[str, Any]) -> tuple[str, int | None, int]:
    """(author login, author id, PR number) of the payload's pull request."""
    pr = payload.get("pull_request")
    if not isinstance(pr, dict):
        return "", None, 0
    user = pr.get("user")
    return _login(user), _user_id(user), _int_or_none(pr.get("number")) or 0


def _event_time(value: Any, received_at: datetime) -> str:
    """GitHub's ISO timestamp if it parses, else the receipt time (ISO)."""
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None or timezone.is_naive(parsed):
        parsed = received_at
    return parsed.isoformat()


class TrustChecker:
    """
    Decides whose feedback counts on one repository and pull request.

    Trusted: the DevMind user who connected the repository (matched by
    GitHub user id, never by login: a renamed owner's old login can be
    taken by someone else), the repository
    owner (author_association OWNER) and users whose repository permission
    is write or admin. MEMBER and COLLABORATOR don't imply write access (an
    organization member can have read-only access, and a collaborator can be
    invited with the read role), so they, and anyone without an
    association, are checked with GET /collaborators/{user}/permission.
    Other associations (CONTRIBUTOR, FIRST_TIME_CONTRIBUTOR, NONE, ...) and
    bot accounts are never trusted. The pull request's own author is never
    trusted on that pull request, so the person being reviewed can't silence
    its findings. Permission lookups are cached for the checker's lifetime
    (one task run).
    """

    def __init__(
        self, repo, pr_author: str, service=None, pr_author_id: int | None = None
    ) -> None:
        self._repo = repo
        self._pr_author = pr_author.lower()
        self._pr_author_id = pr_author_id
        self._owner_id = _int_or_none(getattr(repo.owner, "github_id", None))
        self._service = service
        self._cache: dict[str, bool] = {}

    def is_trusted(
        self,
        login: str,
        association: str | None = None,
        user_type: str = "",
        user_id: int | None = None,
    ) -> bool:
        key = login.lower()
        if not key or user_type == "Bot":
            return False
        if not self._pr_author and self._pr_author_id is None:
            return False
        if key == self._pr_author or (
            user_id is not None and user_id == self._pr_author_id
        ):
            return False
        if self._owner_id is not None and user_id == self._owner_id:
            return True
        if association is not None:
            if association not in TRUSTED_ASSOCIATIONS:
                return False
            if association == "OWNER":
                return True
        if key not in self._cache:
            if self._service is None:
                return False
            permission = self._service.get_collaborator_permission(
                self._repo.full_name, login
            )
            self._cache[key] = permission in WRITE_PERMISSIONS
        return self._cache[key]


def _service_for(repo):
    """GitHubService with the repository owner's token, or None without one."""
    from apps.repositories.services import GitHubService

    github_token = getattr(repo.owner, "github_token", None)
    if github_token is None:
        return None
    return GitHubService(access_token=github_token.access_token, user=repo.owner)


def parse_review_thread_event(
    payload: dict[str, Any], received_at: datetime | None = None
) -> dict[str, Any] | None:
    """
    pull_request_review_thread resolved/unresolved, reduced to what
    apply_feedback_event needs, or None. No database access.
    """
    action = payload.get("action")
    if action not in ("resolved", "unresolved"):
        return None
    repo_github_id = _repo_github_id(payload)
    thread = payload.get("thread")
    if repo_github_id is None or not isinstance(thread, dict):
        return None
    thread_comments = thread.get("comments")
    if not isinstance(thread_comments, list):
        return None
    ids = [
        comment_id
        for comment_id in (
            _int_or_none(item.get("id"))
            for item in thread_comments
            if isinstance(item, dict)
        )
        if comment_id is not None
    ]
    if not ids:
        return None
    pr_author, pr_author_id, pr_number = _pr_fields(payload)
    sender = payload.get("sender")
    return {
        "kind": "thread",
        # The payload has no time for the (un)resolve itself.
        "event_at": (received_at or timezone.now()).isoformat(),
        "actor_id": _user_id(sender),
        "pr_author_id": pr_author_id,
        "action": action,
        "repo_github_id": repo_github_id,
        "comment_ids": ids,
        "actor": _login(sender),
        "user_type": _user_type(sender),
        # The sender has no author_association in this payload.
        "association": None,
        "pr_author": pr_author,
        "pr_number": pr_number,
    }


def parse_review_comment_event(
    payload: dict[str, Any], received_at: datetime | None = None
) -> dict[str, Any] | None:
    """
    A created, edited or deleted reply to an inline comment, reduced to what
    apply_feedback_event needs, or None (not a reply, or a new reply with
    no verdict). No database access.
    """
    action = payload.get("action")
    if action not in ("created", "edited", "deleted"):
        return None
    repo_github_id = _repo_github_id(payload)
    reply = payload.get("comment")
    if repo_github_id is None or not isinstance(reply, dict):
        return None
    parent_id = _int_or_none(reply.get("in_reply_to_id"))
    reply_id = _int_or_none(reply.get("id"))
    if parent_id is None or reply_id is None:
        return None
    signal = None
    if action != "deleted":
        signal = classify_reply(str(reply.get("body") or ""))
        if signal is None and action == "created":
            return None
    pr_author, pr_author_id, pr_number = _pr_fields(payload)
    user = reply.get("user")
    received_at = received_at or timezone.now()
    return {
        "kind": "reply",
        # Created/edited: the reply's updated_at; deleted: the receipt
        # time (its updated_at is the last edit, before the deletion).
        "event_at": (
            received_at.isoformat()
            if action == "deleted"
            else _event_time(reply.get("updated_at"), received_at)
        ),
        "actor_id": _user_id(user),
        "pr_author_id": pr_author_id,
        "action": action,
        "repo_github_id": repo_github_id,
        "comment_ids": [parent_id],
        "reply_id": reply_id,
        "signal": signal,
        "actor": _login(user),
        "user_type": _user_type(user),
        "association": str(reply.get("author_association") or "NONE"),
        "pr_author": pr_author,
        "pr_number": pr_number,
    }


def _remove_reply_verdict(
    comment: ReviewComment, reply_id: int, event_at: datetime, deleted: bool
) -> bool:
    """
    Clear the comment's reply verdict if this reply gave it. A deleted
    reply is remembered (DeletedFeedbackReply), so its created or edited
    event arriving late is ignored.
    """
    if deleted:
        DeletedFeedbackReply.objects.get_or_create(
            github_reply_id=reply_id, defaults={"deleted_at": event_at}
        )
    if not CommentFeedback.objects.filter(
        comment=comment,
        source="reply",
        source_github_id=reply_id,
        signal__isnull=False,
    ).exists():
        return False
    return record_feedback(comment, "reply", None, reply_id, event_at)


def apply_feedback_event(event: dict[str, Any]) -> bool:
    """
    Record a parsed thread or reply event on a DevMind comment.

    Setting a verdict needs a trusted actor (TrustChecker). Deleting a
    reply, or editing it so it has no verdict, removes the verdict that
    reply gave, whoever does it. Returns True when feedback was recorded or
    removed. May raise GitHubRateLimitError (permission lookups).
    """
    from apps.repositories.models import Repository

    repo = (
        Repository.objects.active()
        .select_related("owner")
        .filter(github_id=event["repo_github_id"])
        .first()
    )
    if repo is None:
        return False
    comment = _find_comment(repo.github_id, event["comment_ids"])
    if comment is None:
        return False

    event_at = parse_datetime(event.get("event_at") or "") or timezone.now()
    if event["kind"] == "reply":
        if event["signal"] is None:
            return _remove_reply_verdict(
                comment, event["reply_id"], event_at, event["action"] == "deleted"
            )
        if DeletedFeedbackReply.objects.filter(
            github_reply_id=event["reply_id"]
        ).exists():
            logger.info("feedback.deleted_reply_event comment_id=%d", comment.pk)
            return False

    checker = TrustChecker(
        repo,
        event.get("pr_author") or "",
        _service_for(repo),
        pr_author_id=event.get("pr_author_id"),
    )
    if not checker.is_trusted(
        event.get("actor") or "",
        event.get("association"),
        event.get("user_type", ""),
        user_id=event.get("actor_id"),
    ):
        logger.info(
            "feedback.untrusted_actor comment_id=%d kind=%s",
            comment.pk,
            event["kind"],
        )
        return False

    if event["kind"] == "reply":
        record_feedback(
            comment,
            "reply",
            event["signal"],
            source_github_id=event["reply_id"],
            event_at=event_at,
        )
    else:
        record_feedback(
            comment,
            "resolved",
            ACCEPTED if event["action"] == "resolved" else None,
            event_at=event_at,
        )
    return True


def fetch_reaction_feedback(
    repo_id: int,
    pr_number: int,
    pr_author: str = "",
    pr_author_id: int | None = None,
) -> int:
    """
    Count trusted 👍/👎 on DevMind's inline comments of a closed PR and
    record them.

    One paginated call lists the PR's comments with reaction counts. Only
    comments with a 👍 or 👎 then get their reactions listed (with users),
    and only reactions from trusted users count (TrustChecker; the PR's own
    author never counts). Comments whose counts dropped to zero lose their
    reaction verdict without another call. Comments missing on GitHub
    (deleted) keep any earlier verdict. Every call stays within the quota
    floor. Returns how many comments were checked. Raises
    GitHubRateLimitError when the quota is low.
    """
    from apps.repositories.models import Repository

    repo = (
        Repository.objects.active().select_related("owner").filter(pk=repo_id).first()
    )
    if repo is None:
        return 0
    comments = list(
        ReviewComment.objects.filter(
            review__repository=repo,
            review__pr_number=pr_number,
            github_comment_id__isnull=False,
        )
    )
    if not comments:
        return 0

    service = _service_for(repo)
    if service is None:
        logger.warning("feedback.reactions.no_token repo_id=%d", repo_id)
        return 0
    if not pr_author:
        author = service.get_pull_request_author(repo.full_name, pr_number)
        pr_author, pr_author_id = _login(author), _user_id(author)
    checker = TrustChecker(repo, pr_author, service, pr_author_id=pr_author_id)
    items = service.list_pull_request_review_comments(repo.full_name, pr_number)
    by_id = {
        _int_or_none(item.get("id")): item for item in items if isinstance(item, dict)
    }

    checked = 0
    for comment in comments:
        item = by_id.get(comment.github_comment_id)
        if item is None:
            continue
        rollup = item.get("reactions") or {}
        plus = minus = 0
        if (_int_or_none(rollup.get("+1")) or 0) or (
            _int_or_none(rollup.get("-1")) or 0
        ):
            for reaction in service.list_review_comment_reactions(
                repo.full_name, comment.github_comment_id
            ):
                content = (
                    reaction.get("content") if isinstance(reaction, dict) else None
                )
                if content not in ("+1", "-1"):
                    continue
                user = reaction.get("user")
                if not checker.is_trusted(
                    _login(user), None, _user_type(user), user_id=_user_id(user)
                ):
                    continue
                if content == "+1":
                    plus += 1
                else:
                    minus += 1
        record_feedback(comment, "reaction", classify_reactions(plus, minus))
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
        # FastAPI leaves this PR's own examples out of its later reviews.
        "pr_number": comment.review.pr_number,
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
