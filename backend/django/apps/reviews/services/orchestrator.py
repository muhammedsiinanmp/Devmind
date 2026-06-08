import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.reviews.models import Review, ReviewComment, ReviewRun

logger = logging.getLogger(__name__)

VALID_CATEGORIES = frozenset({"security", "quality", "tests", "style", "performance"})
VALID_SEVERITIES = frozenset({"info", "warning", "error", "critical"})


class ReviewAlreadyProcessingError(Exception):
    """Raised when a review is already being processed."""

    pass


class FastAPIError(Exception):
    """Raised when FastAPI call fails."""

    pass


@dataclass
class ReviewResult:
    """Result from FastAPI review."""

    repo_full_name: str
    pr_number: int
    comments: list[dict] = field(default_factory=list)
    risk_score: int = 0
    model_used: str = ""
    provider: str = ""
    latency_ms: int = 0
    # FIX (Bug 2b): added token counts and agent_iterations
    prompt_tokens: int = 0
    completion_tokens: int = 0
    agent_iterations: int = 1


class ReviewOrchestrator:
    """
    Orchestrates reviews between Django and FastAPI.
    Status transitions: pending → processing → completed | failed
    """

    def __init__(self, review: Review):
        self.review = review
        self.fastapi_url = getattr(
            settings, "FASTAPI_BASE_URL", "http://fastapi:8001"
        ).rstrip("/")
        self.fastapi_secret = getattr(settings, "FASTAPI_INTERNAL_SECRET", "")
        # FIX (Bug 3A): warn loudly on startup so misconfiguration is visible
        if not self.fastapi_secret:
            logger.error(
                "FASTAPI_INTERNAL_SECRET is not set or empty. "
                "All calls to FastAPI /review/analyze will be rejected with 403. "
                "Set FASTAPI_INTERNAL_SECRET in your .env file."
            )
        # FIX (Bug 3C): read timeout from settings instead of hard-coding 60s
        self.timeout = float(getattr(settings, "FASTAPI_TIMEOUT_SECONDS", 120))

    def run(self) -> ReviewResult:
        """
        Run the full review pipeline.
        Status machine: pending → processing → completed | failed
        """
        if self.review.status != "pending":
            if self.review.status == "processing":
                raise ReviewAlreadyProcessingError(
                    f"Review #{self.review.pk} is already being processed"
                )
            raise FastAPIError(
                f"Review #{self.review.pk} is in invalid state: {self.review.status}"
            )

        self.review.status = "processing"
        self.review.save(update_fields=["status"])
        self._push_status_to_channels("processing")
        self._push_status_to_supabase("processing")

        try:
            diff = self._fetch_diff()
            result = self._call_fastapi(diff)
            self._save_results(result)

            self.review.status = "completed"
            self.review.risk_score = result.risk_score
            self.review.summary = self._build_summary(result.comments)
            self.review.completed_at = timezone.now()
            self.review.save(
                update_fields=["status", "risk_score", "summary", "completed_at"]
            )

            self._push_status_to_channels(
                "completed",
                {"summary": self.review.summary, "risk_score": self.review.risk_score},
            )
            self._push_status_to_supabase("completed")
            self._trigger_github_post()
            self._produce_kafka_event()

            return result

        except Exception as exc:
            self.review.status = "failed"
            self.review.summary = f"Error: {str(exc)[:500]}"
            self.review.save(update_fields=["status", "summary"])
            self._push_status_to_channels("failed", {"error": str(exc)[:200]})
            self._push_status_to_supabase("failed")
            raise

    def _fetch_diff(self) -> str:
        """Fetch diff from GitHub."""
        try:
            from apps.repositories.services import GitHubService

            repo = self.review.repository
            github_service = GitHubService(
                access_token=repo.owner.github_token.access_token,
                user=repo.owner,
            )
            return github_service.get_pull_request_diff(
                repo_full_name=repo.full_name,
                pr_number=self.review.pr_number,
            )
        except Exception as e:
            logger.error(
                "orchestrator.fetch_diff.error repo=%s pr=%d error=%s",
                self.review.repository.full_name,
                self.review.pr_number,
                str(e),
            )
            raise FastAPIError(f"Failed to fetch diff: {e}")

    def _call_fastapi(self, diff: str) -> ReviewResult:
        """
        Call FastAPI /review/analyze with retry logic.

        FIX (Bug 3A): guard against empty secret.
        FIX (Bug 3B): retry up to 3 times on 503 with exponential back-off.
        FIX (Bug 3C): use self.timeout instead of hard-coded 60.
        """
        # FIX 3A: fail fast with a clear message instead of a cryptic 403
        if not self.fastapi_secret:
            raise FastAPIError(
                "FASTAPI_INTERNAL_SECRET is empty — the FastAPI service will "
                "reject this request with 403. Configure this value in .env."
            )

        payload = {
            "diff": diff,
            "repo_full_name": self.review.repository.full_name,
            "pr_number": self.review.pr_number,
            "user_id": self.review.repository.owner_id,
        }
        headers = {
            "X-Internal-Secret": self.fastapi_secret,
            "Content-Type": "application/json",
        }

        # FIX 3B: retry on 503 / timeout
        max_retries = 3
        backoff = 5.0

        for attempt in range(1, max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        f"{self.fastapi_url}/review/analyze",
                        json=payload,
                        headers=headers,
                    )

                if response.status_code == 200:
                    data = response.json()
                    return ReviewResult(
                        repo_full_name=data.get("repo_full_name", ""),
                        pr_number=data.get("pr_number", 0),
                        comments=data.get("comments", []),
                        risk_score=data.get("risk_score", 0),
                        model_used=data.get("model_used", ""),
                        provider=data.get("provider", ""),
                        latency_ms=data.get("latency_ms", 0),
                        # FIX 2b: extract token counts from response
                        prompt_tokens=data.get("prompt_tokens", 0),
                        completion_tokens=data.get("completion_tokens", 0),
                        agent_iterations=data.get("agent_iterations", 1),
                    )

                if response.status_code == 403:
                    # Secret mismatch — retrying won't help
                    raise FastAPIError(
                        "FastAPI rejected the request with 403 Forbidden. "
                        "Verify that FASTAPI_INTERNAL_SECRET is identical in "
                        "both Django .env and FastAPI .env."
                    )

                if response.status_code == 429:
                    # LLM providers are rate limited — fast retries won't help,
                    # the rate limit window is ~60s. Raise immediately so Celery's
                    # retry (default_retry_delay=60) handles the backoff correctly.
                    raise FastAPIError(
                        "LLM providers rate limited (429). Celery will retry in 60s."
                    )

                if response.status_code == 503:
                    logger.warning(
                        "orchestrator.fastapi.503 attempt=%d/%d review_id=%d",
                        attempt,
                        max_retries,
                        self.review.pk,
                    )
                    if attempt < max_retries:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    raise FastAPIError(
                        f"All LLM providers unavailable (503 after {max_retries} attempts)."
                    )

                raise FastAPIError(
                    f"FastAPI error {response.status_code}: {response.text[:200]}"
                )

            except httpx.TimeoutException:
                logger.warning(
                    "orchestrator.fastapi.timeout attempt=%d/%d review_id=%d timeout=%.0fs",
                    attempt,
                    max_retries,
                    self.review.pk,
                    self.timeout,
                )
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise FastAPIError(
                    f"FastAPI timed out after {self.timeout}s ({max_retries} attempts)."
                )

            except httpx.HTTPError as exc:
                logger.error(
                    "orchestrator.fastapi.http_error review_id=%d error=%s",
                    self.review.pk,
                    str(exc),
                )
                raise FastAPIError(f"FastAPI HTTP error: {exc}")

        raise FastAPIError("FastAPI call failed after all retries.")

    @transaction.atomic
    def _save_results(self, result: ReviewResult) -> None:
        """
        Save ReviewRun and ReviewComment records.

        FIX (Bug 2a): validate category and severity — unknown values are
                      mapped to safe defaults instead of storing invalid data.
        FIX (Bug 2b): populate prompt_tokens, completion_tokens,
                      agent_iterations on ReviewRun.
        """
        ReviewRun.objects.create(
            review=self.review,
            # FIX 2b: these were always 0 before
            agent_iterations=result.agent_iterations,
            model_used=result.model_used,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=result.latency_ms,
        )

        for comment_data in result.comments:
            # FIX 2a: validate category
            raw_category = comment_data.get("category", "")
            category = raw_category if raw_category in VALID_CATEGORIES else "quality"

            # FIX 2a: validate severity
            raw_severity = comment_data.get("severity", "")
            severity = raw_severity if raw_severity in VALID_SEVERITIES else "info"

            ReviewComment.objects.create(
                review=self.review,
                file_path=comment_data.get("file_path", ""),
                line_number=comment_data.get("line_number", 0),
                category=category,
                severity=severity,
                body=comment_data.get("body", ""),
                suggested_fix=comment_data.get("suggested_fix", "") or "",
            )

    def _build_summary(self, comments: list[dict]) -> str:
        """Build a human-readable summary from comment severities."""
        if not comments:
            return "No issues found."

        critical = sum(1 for c in comments if c.get("severity") == "critical")
        errors = sum(1 for c in comments if c.get("severity") == "error")
        warnings = sum(1 for c in comments if c.get("severity") == "warning")

        parts = []
        if critical:
            parts.append(f"{critical} critical")
        if errors:
            parts.append(f"{errors} error(s)")
        if warnings:
            parts.append(f"{warnings} warning(s)")

        return ", ".join(parts) if parts else "Review complete."

    def _trigger_github_post(self) -> None:
        """Trigger async Celery task to post comments to GitHub."""
        try:
            from apps.reviews.tasks import post_github_comments_task

            post_github_comments_task.delay(self.review.pk)
            logger.info(
                "orchestrator.github_post_triggered review_id=%d", self.review.pk
            )
        except Exception as e:
            logger.error(
                "orchestrator.github_post_failed review_id=%d error=%s",
                self.review.pk,
                str(e),
            )

    def _produce_kafka_event(self) -> None:
        """Produce review.completed event to Kafka (fire-and-forget)."""
        try:
            from devmind.kafka import produce, TOPIC_REVIEW_COMPLETED

            payload = {
                "review_id": self.review.pk,
                "repository_full_name": self.review.repository.full_name,
                "pr_number": self.review.pr_number,
                "pr_title": self.review.pr_title,
                "head_sha": self.review.head_sha,
                "status": self.review.status,
                "risk_score": self.review.risk_score,
                "summary": self.review.summary,
                "completed_at": (
                    self.review.completed_at.isoformat()
                    if self.review.completed_at
                    else None
                ),
            }
            produce(TOPIC_REVIEW_COMPLETED, payload)
        except Exception as e:
            logger.error(
                "orchestrator.kafka_event_failed review_id=%d error=%s",
                self.review.pk,
                str(e),
            )

    def _push_status_to_channels(self, status: str, extra: dict | None = None) -> None:
        """Push status update to WebSocket channel group."""
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer

            channel_layer = get_channel_layer()
            group_name = f"review_{self.review.pk}"
            message = {
                "type": "review.status.update",
                "review_id": self.review.pk,
                "status": status,
            }
            if extra:
                message.update(extra)

            async_to_sync(channel_layer.group_send)(group_name, message)
        except Exception as e:
            logger.error(
                "orchestrator.channel_push_failed review_id=%d error=%s",
                self.review.pk,
                str(e),
            )

    def _push_status_to_supabase(self, status: str) -> None:
        """Insert status update into Supabase (optional — skipped if not configured)."""
        supabase_url = getattr(settings, "SUPABASE_URL", None)
        supabase_key = getattr(settings, "SUPABASE_SERVICE_KEY", None)
        if not supabase_url or not supabase_key:
            return

        try:
            from asgiref.sync import async_to_sync

            async def _insert():
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        f"{supabase_url}/rest/v1/review_status_updates",
                        json={
                            "review_id": self.review.pk,
                            "status": status,
                            "summary": self.review.summary or "",
                            "risk_score": self.review.risk_score or 0,
                            "updated_at": timezone.now().isoformat(),
                        },
                        headers={
                            "apikey": supabase_key,
                            "Authorization": f"Bearer {supabase_key}",
                            "Content-Type": "application/json",
                            "Prefer": "return=minimal",
                        },
                    )

            async_to_sync(_insert)()
        except Exception as e:
            logger.error(
                "orchestrator.supabase_push_failed review_id=%d error=%s",
                self.review.pk,
                str(e),
            )


def trigger_review_task(review_id: int) -> None:
    """Standalone function wrapper used by reviews/tasks.py."""
    try:
        review = Review.objects.get(pk=review_id)
        orchestrator = ReviewOrchestrator(review)
        orchestrator.run()
    except ReviewAlreadyProcessingError:
        logger.warning("review.already_processing id=%d", review_id)
    except Exception as e:
        logger.error("review.task.error id=%d error=%s", review_id, str(e))
        raise
