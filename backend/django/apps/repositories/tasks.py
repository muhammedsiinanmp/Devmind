"""
Celery tasks for repository management.

Task design rules:
1. Tasks are thin orchestrators — all business logic lives in services.py.
2. All DB access is via the ORM only — no raw SQL.
3. Use self.retry(exc=exc) for retriable failures. Set max_retries explicitly.
4. Log the task start, success, and failure to structlog for observability.
5. Mark tasks idempotent where possible (install_webhook_task checks existing state).
"""

from __future__ import annotations

import structlog
from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.repositories.exceptions import GitHubRateLimitError, GitHubServiceError
from apps.repositories.models import Repository
from apps.repositories.services import GitHubService

log: structlog.BoundLogger = structlog.get_logger(__name__)
User = get_user_model()

# Delay on rate limit — wait for GitHub reset window
RATE_LIMIT_RETRY_COUNTDOWN = 3600  # 1 hour


@shared_task(
    bind=True,
    name="repositories.initial_sync",
    queue="default",
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=300,  # 5 minutes
    time_limit=360,
    acks_late=True,  # Task re-queued if worker crashes mid-execution
)
def initial_repository_sync_task(
    self: "initial_repository_sync_task", user_id: int
) -> None:
    """
    Fetches all GitHub repositories for a user and upserts them to the DB.
    Enqueued after OAuth login completes — never blocks the request-response cycle.
    """
    log.info("task.initial_sync.start", user_id=user_id)

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        log.error("task.initial_sync.user_not_found", user_id=user_id)
        return  # Non-retriable — user was deleted

    try:
        github_token = user.githubtoken  # type: ignore[attr-defined]
    except Exception:
        log.error("task.initial_sync.no_token", user_id=user_id)
        return

    try:
        service = GitHubService(
            access_token=github_token.access_token,
            user=user,
        )
        repos_data = service.fetch_user_repositories()
    except GitHubRateLimitError as exc:
        log.warning(
            "task.initial_sync.rate_limited",
            user_id=user_id,
            reset_at=exc.reset_at,
        )
        raise self.retry(exc=exc, countdown=RATE_LIMIT_RETRY_COUNTDOWN)
    except GitHubServiceError as exc:
        log.error("task.initial_sync.github_error", user_id=user_id, error=str(exc))
        raise self.retry(exc=exc)

    created_count = 0
    updated_count = 0

    for repo_data in repos_data:
        repo, created = Repository.objects.update_or_create(
            github_id=repo_data.github_id,
            defaults={
                "owner": user,
                "full_name": repo_data.full_name,
                "name": repo_data.name,
                "description": repo_data.description or "",
                "is_private": repo_data.is_private,
                "default_branch": repo_data.default_branch,
                "html_url": repo_data.html_url,
                "clone_url": repo_data.clone_url,
                "language": repo_data.language or "",
                "topics": repo_data.topics,
                "stargazers_count": repo_data.stargazers_count,
                "last_synced_at": timezone.now(),
            },
        )
        if created:
            created_count += 1
            # Enqueue webhook installation for new repositories
            install_webhook_task.delay(repo_id=repo.pk)
        else:
            updated_count += 1

    log.info(
        "task.initial_sync.complete",
        user_id=user_id,
        created=created_count,
        updated=updated_count,
    )


@shared_task(
    bind=True,
    name="repositories.install_webhook",
    queue="default",
    max_retries=5,
    default_retry_delay=30,
    acks_late=True,
)
def install_webhook_task(self: "install_webhook_task", repo_id: int) -> None:
    """
    Installs a GitHub webhook for a repository.
    Idempotent: skips if webhook_id is already set.
    """
    try:
        repo = Repository.objects.select_related("owner").get(pk=repo_id)
    except Repository.DoesNotExist:
        log.error("task.install_webhook.repo_not_found", repo_id=repo_id)
        return

    if repo.has_webhook():
        log.info(
            "task.install_webhook.already_installed",
            repo=repo.full_name,
            webhook_id=repo.webhook_id,
        )
        return

    log.info("task.install_webhook.start", repo=repo.full_name)

    try:
        github_token = repo.owner.githubtoken  # type: ignore[attr-defined]
        service = GitHubService(
            access_token=github_token.access_token,
            user=repo.owner,
        )
        result = service.install_webhook(repo.full_name)
    except GitHubRateLimitError as exc:
        raise self.retry(exc=exc, countdown=RATE_LIMIT_RETRY_COUNTDOWN)
    except GitHubServiceError as exc:
        log.error(
            "task.install_webhook.failed",
            repo=repo.full_name,
            error=str(exc),
        )
        raise self.retry(exc=exc)

    repo.webhook_id = result.webhook_id
    repo.save(update_fields=["webhook_id", "updated_at"])

    log.info(
        "task.install_webhook.complete",
        repo=repo.full_name,
        webhook_id=result.webhook_id,
    )


@shared_task(
    bind=True,
    name="repositories.remove_webhook",
    queue="default",
    max_retries=3,
    acks_late=True,
)
def remove_webhook_task(self: "remove_webhook_task", repo_id: int) -> None:
    """
    Removes a GitHub webhook for a repository and clears webhook_id.
    Used when a user disconnects a repository from DevMind.
    """
    try:
        repo = Repository.objects.select_related("owner").get(pk=repo_id)
    except Repository.DoesNotExist:
        log.error("task.remove_webhook.repo_not_found", repo_id=repo_id)
        return

    if not repo.has_webhook():
        log.info("task.remove_webhook.no_webhook", repo=repo.full_name)
        return

    log.info(
        "task.remove_webhook.start",
        repo=repo.full_name,
        webhook_id=repo.webhook_id,
    )

    try:
        github_token = repo.owner.githubtoken  # type: ignore[attr-defined]
        service = GitHubService(
            access_token=github_token.access_token,
            user=repo.owner,
        )
        service.delete_webhook(repo.full_name, webhook_id=repo.webhook_id)  # type: ignore[arg-type]
    except GitHubServiceError as exc:
        raise self.retry(exc=exc)

    repo.webhook_id = None
    repo.save(update_fields=["webhook_id", "updated_at"])

    log.info("task.remove_webhook.complete", repo=repo.full_name)


@shared_task(
    name="repositories.trigger_review",
    queue="review",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def trigger_review_task(repo_id: int, pr_number: int, head_sha: str) -> None:
    """
    Placeholder for Phase 4 review orchestration.
    Enqueued by WebhookDispatcher when a PR is opened/updated.
    Phase 4 will fill this with the ReviewOrchestrator call.
    """
    log.info(
        "task.trigger_review.received",
        repo_id=repo_id,
        pr_number=pr_number,
        head_sha=head_sha[:8],
    )
    # Phase 4 implementation goes here
