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
from typing import TYPE_CHECKING

import structlog
from django.conf import settings
from django.http import HttpRequest

from apps.repositories.exceptions import WebhookVerificationError
from apps.repositories.models import Repository
from apps.repositories.types import GitHubPayload

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

    secret: bytes = settings.GITHUB_WEBHOOK_SECRET.encode("utf-8")
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
        Unknown event types are silently ignored (GitHub sends many we don't care about).
        """
        log.debug("webhook.event.received", event_type=event_type)

        if event_type == "pull_request":
            self._handle_pull_request(payload)
        elif event_type == "ping":
            log.info("webhook.ping.received")
        else:
            log.debug("webhook.event.ignored", event_type=event_type)

    def _handle_pull_request(self, payload: GitHubPayload) -> None:
        """
        Handles pull_request events.
        Only routes opened/synchronize/reopened actions to review processing.
        Closed, labeled, review_requested, etc. are ignored.
        """
        # Import here to avoid circular imports
        from apps.repositories.tasks import trigger_review_task

        action = str(payload.get("action", ""))
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
        )
