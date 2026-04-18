from rest_framework import serializers

from apps.accounts.models import CustomUser


class UserSerializer(serializers.ModelSerializer):
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


class TokenPairSerializer(serializers.Serializer):
    """Serializer for JWT token pair response."""

    access = serializers.CharField(help_text="JWT access token")
    refresh = serializers.CharField(help_text="JWT refresh token")
