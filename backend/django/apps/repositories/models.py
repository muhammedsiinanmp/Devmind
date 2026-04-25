from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.repositories.managers import RepositoryManager


class Repository(models.Model):
    """
    A GitHub repository connected to DevMind by a user.

    Design decisions:
    - github_id is the stable canonical key (survives repo renames).
    - webhook_id is nullable: None = webhook not yet installed.
    - is_active is a "Kill Switch": disabling stops AI reviews without data loss.
    - review_enabled gives per-repo control independent of the kill switch.
    - last_synced_at tracks background sync health for operational monitoring.
    """

    github_id = models.BigIntegerField(
        unique=True,
        help_text="GitHub's immutable numeric repository ID.",
    )
    full_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="GitHub full name, e.g. 'acme/api'. May change on rename.",
    )
    name = models.CharField(
        max_length=100,
        help_text="Short repository name without owner prefix.",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="repositories",
    )
    description = models.TextField(blank=True, default="")
    is_private = models.BooleanField(default=False)
    default_branch = models.CharField(max_length=255, default="main")
    html_url = models.URLField(max_length=500)
    clone_url = models.URLField(max_length=500)
    language = models.CharField(max_length=100, blank=True, default="")
    topics = models.JSONField(default=list, blank=True)
    stargazers_count = models.PositiveIntegerField(default=0)

    # Webhook state — None means not installed
    webhook_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="GitHub webhook ID for this repo. Null if not installed.",
    )

    # Feature toggles
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Kill switch: False disables all DevMind processing for this repo.",
    )
    review_enabled = models.BooleanField(
        default=True,
        help_text="Whether AI code review is enabled for pull requests.",
    )

    # Operational timestamps
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When repository metadata was last synced from GitHub.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects: RepositoryManager = RepositoryManager()

    class Meta:
        verbose_name_plural = "repositories"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "is_active"]),
            models.Index(fields=["github_id"]),
        ]

    def __str__(self) -> str:
        return self.full_name

    def has_webhook(self) -> bool:
        """Returns True if a GitHub webhook is installed for this repository."""
        return self.webhook_id is not None
