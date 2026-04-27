from __future__ import annotations

from rest_framework import serializers

from apps.repositories.models import Repository


class RepositorySerializer(serializers.ModelSerializer[Repository]):
    """Read serializer — exposes all repository metadata."""

    has_webhook = serializers.SerializerMethodField()

    class Meta:
        model = Repository
        fields = [
            "id",
            "github_id",
            "full_name",
            "name",
            "description",
            "is_private",
            "default_branch",
            "html_url",
            "language",
            "topics",
            "stargazers_count",
            "is_active",
            "review_enabled",
            "has_webhook",
            "last_synced_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "github_id",
            "full_name",
            "name",
            "html_url",
            "is_active",  # toggled via dedicated endpoint
            "has_webhook",
            "last_synced_at",
            "created_at",
            "updated_at",
        ]

    def get_has_webhook(self, obj: Repository) -> bool:
        return obj.has_webhook()


class RepositoryUpdateSerializer(serializers.ModelSerializer[Repository]):
    """
    Write serializer for user-controlled fields.
    Intentionally narrow — users cannot change github_id, owner, etc.
    """

    class Meta:
        model = Repository
        fields = ["review_enabled", "default_branch"]
