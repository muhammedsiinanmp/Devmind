"""
Review Orchestrator — Django/FastAPI bridge.

Orchestrates the full review pipeline: fetch diff → call FastAPI → save results.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.reviews.models import Review, ReviewComment, ReviewRun

logger = logging.getLogger(__name__)


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


class ReviewOrchestrator:
    """
    Orchestrates reviews between Django and FastAPI.

    Handles status transitions: pending → processing → completed/failed
    """

    def __init__(self, review: Review):
        self.review = review
        self.fastapi_url = getattr(settings, "FASTAPI_URL", "http://localhost:8000")
        self.fastapi_secret = getattr(settings, "FASTAPI_INTERNAL_SECRET", "")

    @transaction.atomic
    def run(self) -> ReviewResult:
        """
        Run the full review pipeline.

        Args:
            review: Review instance

        Returns:
            ReviewResult from FastAPI

        Raises:
            ReviewAlreadyProcessingError: If review is already processing
            FastAPIError: If FastAPI call fails
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
            from apps.repositories.services.github import GithubService

            repo = self.review.repository
            github_service = GithubService(repo.owner.github_token)

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
        """Call FastAPI /review/analyze endpoint."""
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.fastapi_url}/review/analyze",
                    json={
                        "diff": diff,
                        "repo_full_name": self.review.repository.full_name,
                        "pr_number": self.review.pr_number,
                    },
                    headers={
                        "X-Internal-Secret": self.fastapi_secret,
                        "Content-Type": "application/json",
                    },
                )

                if response.status_code == 503:
                    raise FastAPIError("All LLM providers unavailable")

                if response.status_code != 200:
                    raise FastAPIError(f"FastAPI error: {response.status_code}")

                data = response.json()

                return ReviewResult(
                    repo_full_name=data.get("repo_full_name", ""),
                    pr_number=data.get("pr_number", 0),
                    comments=data.get("comments", []),
                    risk_score=data.get("risk_score", 0),
                    model_used=data.get("model_used", ""),
                    provider=data.get("provider", ""),
                    latency_ms=data.get("latency_ms", 0),
                )

        except httpx.TimeoutException:
            raise FastAPIError("FastAPI request timed out")
        except httpx.HTTPError as e:
            logger.error("orchestrator.fastapi.error error=%s", str(e))
            raise FastAPIError(f"FastAPI HTTP error: {e}")

    @transaction.atomic
    def _save_results(self, result: ReviewResult) -> None:
        """Save comments and run record."""
        run = ReviewRun.objects.create(
            review=self.review,
            model_used=result.model_used,
            provider=result.provider,
            latency_ms=result.latency_ms,
            risk_score=result.risk_score,
        )

        for comment_data in result.comments:
            ReviewComment.objects.create(
                review=self.review,
                file_path=comment_data.get("file_path", ""),
                line_number=comment_data.get("line_number", 0),
                category=comment_data.get("category", "general"),
                severity=comment_data.get("severity", "info"),
                body=comment_data.get("body", ""),
                suggested_fix=comment_data.get("suggested_fix"),
                run=run,
            )

    def _build_summary(self, comments: list[dict]) -> str:
        """Build summary from comments."""
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
        """Trigger async task to post comments to GitHub."""
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
        """Produce review completed event to Kafka."""
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
            logger.info(
                "orchestrator.kafka_event_produced review_id=%d", self.review.pk
            )
        except Exception as e:
            logger.error(
                "orchestrator.kafka_event_failed review_id=%d error=%s",
                self.review.pk,
                str(e),
            )

    def _push_status_to_channels(self, status: str, extra: dict | None = None) -> None:
        """Push status update to WebSocket channels."""
        try:
            import asyncio
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer

            channel_layer = get_channel_layer()
            group_name = f"review_{self.review.pk}"

            message = {
                "review_id": self.review.pk,
                "status": status,
            }
            if extra:
                message.update(extra)

            async def _send():
                await channel_layer.group_send(group_name, message)

            async_to_sync(_send)()
            logger.info(
                "orchestrator.channel_pushed review_id=%d status=%s",
                self.review.pk,
                status,
            )
        except Exception as e:
            logger.error(
                "orchestrator.channel_push_failed review_id=%d error=%s",
                self.review.pk,
                str(e),
            )

    def _push_status_to_supabase(self, status: str) -> None:
        """Insert status update into Supabase review_status_updates table."""
        supabase_url = getattr(settings, "SUPABASE_URL", None)
        supabase_key = getattr(settings, "SUPABASE_SERVICE_KEY", None)

        if not supabase_url or not supabase_key:
            logger.warning("Supabase not configured, skipping status push")
            return

        try:
            import asyncio
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
            logger.info(
                "orchestrator.supabase_pushed review_id=%d status=%s",
                self.review.pk,
                status,
            )
        except Exception as e:
            logger.error(
                "orchestrator.supabase_push_failed review_id=%d error=%s",
                self.review.pk,
                str(e),
            )


def trigger_review_task(review_id: int) -> None:
    """
    Celery task to trigger a review.

    Wraps ReviewOrchestrator.run() for async execution.
    """
    try:
        review = Review.objects.get(pk=review_id)
        orchestrator = ReviewOrchestrator(review)
        orchestrator.run()
    except ReviewAlreadyProcessingError:
        logger.warning("review.already_processing id=%d", review_id)
    except Exception as e:
        logger.error("review.task.error id=%d error=%s", review_id, str(e))
        raise
