"""
GitHub webhook HMAC-SHA256 validation and event dispatching.

Security contract:
  1. verify_webhook_signature() MUST be called before any payload access.
  2. Always use hmac.compare_digest() — never == — to prevent timing attacks.
  3. An invalid signature returns HTTP 403 with an opaque message. Never 400,
     which reveals that the endpoint exists and parsed the request.
  4. Payload deserialization happens ONLY after signature is verified.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog
from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from apps.repositories.exceptions import WebhookVerificationError
from apps.repositories.models import Repository
from apps.repositories.tasks import trigger_review_task
from apps.repositories.types import GitHubPayload
from apps.reviews.services.feedback import (
    parse_review_comment_event,
    parse_review_thread_event,
)
from apps.reviews.tasks import fetch_comment_reactions_task, record_feedback_event_task

if TYPE_CHECKING:
    pass

log: structlog.BoundLogger = structlog.get_logger(__name__)

# Actions that trigger AI review — all others are silently ignored
PR_REVIEW_ACTIONS = frozenset({"opened", "synchronize", "reopened"})


def verify_webhook_signature(request: HttpRequest) -> None:
    """
    Validates the GitHub HMAC-SHA256 webhook signature.

    Raises:
        WebhookVerificationError: If the signature is missing, malformed,
            or does not match the expected HMAC.

    Note:
        This function reads request.body — calling it multiple times is safe
        because Django caches the body after the first read.
    """
    signature_header: str = request.headers.get("X-Hub-Signature-256", "")

    if not signature_header:
        log.warning("webhook.signature.missing", path=request.path)
        raise WebhookVerificationError("Missing X-Hub-Signature-256 header.")

    if not signature_header.startswith("sha256="):
        log.warning(
            "webhook.signature.malformed",
            header_prefix=signature_header[:10],
        )
        raise WebhookVerificationError("Malformed signature header format.")

    configured_secret: str = settings.GITHUB_WEBHOOK_SECRET or ""
    if not configured_secret:
        # An empty HMAC key would let anyone forge a valid signature.
        log.error("webhook.secret.not_configured", path=request.path)
        raise WebhookVerificationError("Webhook secret is not configured.")

    secret: bytes = configured_secret.encode("utf-8")
    body: bytes = request.body

    expected_signature: str = (
        "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    )

    # Constant-time comparison — critical security requirement
    if not hmac.compare_digest(expected_signature, signature_header):
        log.warning(
            "webhook.signature.mismatch",
            remote_addr=request.META.get("REMOTE_ADDR"),
        )
        raise WebhookVerificationError("Signature mismatch.")

    log.debug("webhook.signature.verified")


class WebhookDispatcher:
    """
    Routes verified webhook payloads to the appropriate handler.

    Design note: A class is used instead of module-level functions so that
    test doubles can be injected and handler methods can be overridden.
    """

    def dispatch(self, payload: GitHubPayload, event_type: str) -> None:
        """
        Routes the payload to the appropriate handler based on GitHub event type.
        Unknown event types are silently ignored.
        """
        log.debug("webhook.event.received", event_type=event_type)

        if event_type == "pull_request":
            self._handle_pull_request(payload)
        elif event_type == "pull_request_review_thread":
            self._handle_feedback(parse_review_thread_event, payload, event_type)
        elif event_type == "pull_request_review_comment":
            self._handle_feedback(parse_review_comment_event, payload, event_type)
        elif event_type == "ping":
            log.info("webhook.ping.received")
        else:
            log.debug("webhook.event.ignored", event_type=event_type)

    def _handle_feedback(
        self,
        parse: Callable[..., dict[str, Any] | None],
        payload: Any,
        event_type: str,
    ) -> None:
        """
        Queues a resolved thread or a reply as possible feedback. The task
        checks that it is about a DevMind comment and that the actor is
        trusted, which can need a GitHub call, so it isn't done here.
        """
        if not isinstance(payload, dict):
            return
        # Receipt time: the fallback event time for ordering events.
        event = parse(payload, timezone.now())
        if event is not None:
            record_feedback_event_task.delay(event)
        log.info(
            "webhook.feedback.handled",
            event_type=event_type,
            action=str(payload.get("action", "")),
            queued=event is not None,
        )

    def _handle_pull_request_closed(self, payload: GitHubPayload) -> None:
        """Queues the 👍/👎 count on DevMind's comments of the closed PR."""
        repo_data = payload.get("repository", {})
        pr_data = payload.get("pull_request", {})
        if not isinstance(repo_data, dict) or not isinstance(pr_data, dict):
            return
        try:
            github_id = int(str(repo_data.get("id", 0)))
            pr_number = int(str(pr_data.get("number", 0)))
        except ValueError:
            return
        repo = Repository.objects.active().filter(github_id=github_id).first()
        if repo is None or not pr_number:
            return
        pr_user = pr_data.get("user")
        pr_author = str(pr_user.get("login") or "") if isinstance(pr_user, dict) else ""
        pr_author_id = pr_user.get("id") if isinstance(pr_user, dict) else None
        fetch_comment_reactions_task.delay(
            repo_id=repo.pk,
            pr_number=pr_number,
            pr_author=pr_author,
            pr_author_id=pr_author_id if isinstance(pr_author_id, int) else None,
        )
        log.info(
            "webhook.pr.closed.feedback_queued",
            repo=repo.full_name,
            pr_number=pr_number,
        )

    def _handle_pull_request(self, payload: GitHubPayload) -> None:
        """
        Handles pull_request events.
        Routes opened/synchronize/reopened actions to review processing and
        closed to the feedback reaction count. Labeled, review_requested,
        etc. are ignored.
        """
        action = str(payload.get("action", ""))
        if action == "closed":
            self._handle_pull_request_closed(payload)
            return
        if action not in PR_REVIEW_ACTIONS:
            log.debug("webhook.pr.action.ignored", action=action)
            return

        repo_data = payload.get("repository", {})
        if not isinstance(repo_data, dict):
            log.error("webhook.pr.invalid_repository_payload")
            return

        github_id = int(str(repo_data.get("id", 0)))
        full_name = str(repo_data.get("full_name", ""))

        # Guard: only process repos we know about and have active
        try:
            repo = Repository.objects.active().get(github_id=github_id)
        except Repository.DoesNotExist:
            log.warning(
                "webhook.pr.unknown_repository",
                github_id=github_id,
                full_name=full_name,
            )
            return

        if not repo.review_enabled:
            log.info(
                "webhook.pr.review_disabled",
                repo=full_name,
            )
            return

        pr_data = payload.get("pull_request", {})
        if not isinstance(pr_data, dict):
            log.error("webhook.pr.invalid_pr_payload", repo=full_name)
            return

        pr_number = int(str(pr_data.get("number", 0)))
        head_sha = str(pr_data.get("head", {}).get("sha", ""))  # type: ignore[union-attr]
        pr_title = str(pr_data.get("title", ""))
        base_sha = str(pr_data.get("base", {}).get("sha", ""))  # type: ignore[union-attr]
        diff_url = str(pr_data.get("diff_url", ""))

        log.info(
            "webhook.pr.dispatching_review",
            repo=full_name,
            pr_number=pr_number,
            action=action,
        )

        # Enqueue the review task and return immediately
        # Never do synchronous work in a webhook handler
        trigger_review_task.delay(
            repo_id=repo.pk,
            pr_number=pr_number,
            head_sha=head_sha,
            pr_title=pr_title,
            base_sha=base_sha,
            diff_url=diff_url,
        )
