from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from django.contrib.auth import get_user_model

    User = get_user_model()


class RepositoryQuerySet(models.QuerySet["Repository"]):  # type: ignore[name-defined]
    """Encapsulates all common repository query patterns."""

    def active(self) -> "RepositoryQuerySet":
        """Returns only repositories where is_active=True."""
        return self.filter(is_active=True)

    def for_user(self, user: "User") -> "RepositoryQuerySet":
        """Returns repositories owned by the given user."""
        return self.filter(owner=user)

    def with_webhook(self) -> "RepositoryQuerySet":
        """Returns repositories that have a GitHub webhook installed."""
        return self.exclude(webhook_id__isnull=True)

    def without_webhook(self) -> "RepositoryQuerySet":
        """Returns repositories that need a webhook installed."""
        return self.filter(webhook_id__isnull=True)

    def review_enabled(self) -> "RepositoryQuerySet":
        """Returns repositories where AI review is enabled."""
        return self.filter(review_enabled=True)

    def pending_initial_sync(self) -> "RepositoryQuerySet":
        """Returns active repos that have never been synced."""
        return self.filter(is_active=True, last_synced_at__isnull=True)


class RepositoryManager(models.Manager["Repository"]):  # type: ignore[name-defined]
    def get_queryset(self) -> RepositoryQuerySet:
        return RepositoryQuerySet(self.model, using=self._db)

    def active(self) -> RepositoryQuerySet:
        return self.get_queryset().active()

    def for_user(self, user: "User") -> RepositoryQuerySet:
        return self.get_queryset().for_user(user)

    def with_webhook(self) -> RepositoryQuerySet:
        return self.get_queryset().with_webhook()
