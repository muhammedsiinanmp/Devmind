from typing import TYPE_CHECKING, Any

from rest_framework import serializers

from apps.accounts.models import CustomUser

if TYPE_CHECKING:
    _BaseModelSerializer = serializers.ModelSerializer[CustomUser]
    _BaseSerializer = serializers.Serializer[dict[str, Any]]
else:
    _BaseModelSerializer = serializers.ModelSerializer
    _BaseSerializer = serializers.Serializer


class UserSerializer(_BaseModelSerializer):
    """Read-only serializer for the authenticated user's profile."""

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "email",
            "github_id",
            "github_login",
            "avatar_url",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TokenPairSerializer(_BaseSerializer):
    """Serializer for JWT token pair response."""

    access = serializers.CharField(help_text="JWT access token")
    refresh = serializers.CharField(help_text="JWT refresh token")
