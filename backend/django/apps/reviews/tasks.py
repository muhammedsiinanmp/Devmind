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
        raise self.retry(exc=e)


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
