"""
Celery tasks for reviews.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def trigger_review_task(self, review_id: int):
    """
    Celery task to trigger a review.

    Args:
        review_id: ID of the Review to process

    Raises:
        Exception: Re-raised for Celery retry handling
    """
    try:
        from apps.reviews.services import (
            ReviewOrchestrator,
            ReviewAlreadyProcessingError,
        )
        from apps.reviews.models import Review

        review = Review.objects.get(pk=review_id)
        orchestrator = ReviewOrchestrator(review)
        orchestrator.run()

        logger.info("review.completed review_id=%d", review_id)

    except ReviewAlreadyProcessingError as e:
        logger.warning(
            "review.already_processing review_id=%d error=%s", review_id, str(e)
        )

    except Exception as e:
        logger.error("review.failed review_id=%d error=%s", review_id, str(e))
        # Reset to pending so the orchestrator's state guard allows the retry to run.
        # Only reset when retries remain — on the final attempt leave it as "failed"
        # so the review doesn't get stuck in "pending" with no active task.
        if self.request.retries < self.max_retries:
            try:
                from apps.reviews.models import Review

                Review.objects.filter(pk=review_id, status="failed").update(
                    status="pending"
                )
            except Exception:
                pass
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def post_github_comments_task(self, review_id: int):
    """
    Post review comments to GitHub PR.

    Args:
        review_id: ID of the completed Review

    Note:
        Separate from trigger_review_task - allows retry without re-running review.
    """
    try:
        from apps.reviews.services.github_poster import post_github_comments

        status_codes = post_github_comments(review_id)

        logger.info(
            "github_comments.posted review_id=%d calls=%d",
            review_id,
            len(status_codes),
        )
        return status_codes

    except Exception as e:
        logger.error("github_comments.failed review_id=%d error=%s", review_id, str(e))
        raise self.retry(exc=e)


def rate_limit_countdown(reset_at: int, now: float) -> int:
    """Seconds to wait for GitHub's quota reset: at least 60, at most an hour."""
    return int(min(max(reset_at - now, 60), 3600))


@shared_task(bind=True, max_retries=5, default_retry_delay=60, acks_late=True)
def fetch_comment_reactions_task(
    self, repo_id: int, pr_number: int, pr_author: str = ""
):
    """
    Record trusted 👍/👎 feedback on DevMind's comments when a PR closes.

    On a GitHub rate limit the task waits for the quota reset (up to an
    hour) and runs again; recording is idempotent, so a rerun is safe.
    Errors a retry can't fix (401, a non-rate-limit 403, 404) end the task.
    """
    import time

    from apps.repositories.exceptions import (
        PERMANENT_GITHUB_ERRORS,
        GitHubRateLimitError,
        GitHubServiceError,
    )
    from apps.reviews.services.feedback import fetch_reaction_feedback

    try:
        checked = fetch_reaction_feedback(repo_id, pr_number, pr_author)
    except PERMANENT_GITHUB_ERRORS as exc:
        logger.warning(
            "feedback.reactions.not_retried repo_id=%d pr=%d error=%s",
            repo_id,
            pr_number,
            type(exc).__name__,
        )
        return 0
    except GitHubRateLimitError as exc:
        countdown = rate_limit_countdown(exc.reset_at, time.time())
        logger.warning(
            "feedback.reactions.rate_limited repo_id=%d pr=%d retry_in=%ds",
            repo_id,
            pr_number,
            countdown,
        )
        raise self.retry(exc=exc, countdown=countdown)
    except GitHubServiceError as exc:
        logger.error(
            "feedback.reactions.github_error repo_id=%d pr=%d error=%s",
            repo_id,
            pr_number,
            str(exc),
        )
        raise self.retry(exc=exc)

    logger.info(
        "feedback.reactions.done repo_id=%d pr=%d comments=%d",
        repo_id,
        pr_number,
        checked,
    )
    return checked


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def record_feedback_event_task(self, event: dict):
    """
    Record a reply or resolved-thread event on a DevMind comment
    (services.feedback.apply_feedback_event). A task because checking the
    actor's repository permission calls GitHub.
    """
    import time

    from apps.repositories.exceptions import (
        PERMANENT_GITHUB_ERRORS,
        GitHubRateLimitError,
        GitHubServiceError,
    )
    from apps.reviews.services.feedback import apply_feedback_event

    try:
        return apply_feedback_event(event)
    except PERMANENT_GITHUB_ERRORS as exc:
        logger.warning("feedback.event.not_retried error=%s", type(exc).__name__)
        return False
    except GitHubRateLimitError as exc:
        raise self.retry(
            exc=exc, countdown=rate_limit_countdown(exc.reset_at, time.time())
        )
    except GitHubServiceError as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def sync_comment_feedback_task(self, comment_id: int):
    """Send a comment's feedback verdict to FastAPI for embedding."""
    from apps.reviews.services.feedback import (
        FeedbackSyncError,
        sync_comment_feedback,
    )

    try:
        sync_comment_feedback(comment_id)
    except FeedbackSyncError as exc:
        logger.warning(
            "feedback.sync.failed comment_id=%d error=%s", comment_id, str(exc)
        )
        raise self.retry(exc=exc)


@shared_task
def cleanup_old_reviews(days: int = 30):
    """
    Clean up old completed/failed reviews.

    Args:
        days: Number of days to keep
    """
    from django.utils import timezone
    from datetime import timedelta

    from apps.reviews.models import Review

    cutoff = timezone.now() - timedelta(days=days)
    deleted_count, _ = Review.objects.filter(
        status__in=["completed", "failed"],
        created_at__lt=cutoff,
    ).delete()

    logger.info("reviews.cleanedup count=%d", deleted_count)
    return deleted_count
