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


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def full_repo_scan_task(self, scan_id: int):
    """
    Execute a full repository scan.

    Args:
        scan_id: ID of the RepoScan to process
    """
    try:
        from apps.reviews.models import RepoScan
        from django.conf import settings
        import httpx

        scan = RepoScan.objects.get(pk=scan_id)

        scan.status = "scanning"
        scan.save(update_fields=["status"])

        fastapi_url = getattr(settings, "FASTAPI_BASE_URL", "http://fastapi:8001")
        internal_secret = getattr(settings, "FASTAPI_INTERNAL_SECRET", "")

        response = httpx.post(
            f"{fastapi_url}/scan/full",
            json={
                "repo_full_name": scan.repository.full_name,
                "repo_url": scan.repository.clone_url,
                "branch": scan.repository.default_branch,
            },
            headers={"X-Internal-Secret": internal_secret},
            timeout=float(getattr(settings, "FASTAPI_TIMEOUT_SECONDS", 120)),
        )

        if response.status_code == 202:
            response_data = response.json()
            scan.scan_id = response_data.get("scan_id", scan_id)
            scan.status = "scanning"
            scan.save(update_fields=["scan_id", "status"])
            logger.info("scan.started scan_id=%d", scan.pk)
        else:
            raise Exception(f"FastAPI returned {response.status_code}")

    except Exception as e:
        scan = RepoScan.objects.filter(pk=scan_id).first()
        if scan:
            scan.status = "failed"
            scan.summary = f"Scan failed: {str(e)[:200]}"
            scan.save(update_fields=["status", "summary"])
        logger.error("scan.failed scan_id=%d error=%s", scan_id, str(e))
        raise self.retry(exc=e)
