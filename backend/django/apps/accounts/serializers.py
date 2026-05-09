from typing import TYPE_CHECKING, Any

from rest_framework import serializers

from apps.accounts.models import CustomUser, UserLLMConfig

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


class UserLLMConfigSerializer(_BaseModelSerializer):
    """Serializer for user's LLM API keys (BYOK)."""

    masked_key = serializers.SerializerMethodField()

    class Meta:
        model = UserLLMConfig
        fields = [
            "id",
            "provider",
            "model_name",
            "masked_key",
            "base_url",
            "is_active",
            "priority",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "masked_key", "created_at", "updated_at"]

    def get_masked_key(self, obj: UserLLMConfig) -> str:
        """Return masked API key for display."""
        return obj.masked_key

    def create(self, validated_data: dict) -> UserLLMConfig:
        """Create and encrypt the API key."""
        return super().create(validated_data)


class UserLLMConfigCreateSerializer(_BaseModelSerializer):
    """Serializer for creating a new LLM config."""

    api_key = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = UserLLMConfig
        fields = [
            "provider",
            "model_name",
            "api_key",
            "base_url",
            "is_active",
            "priority",
        ]

    def create(self, validated_data: dict) -> UserLLMConfig:
        """Create and encrypt the API key."""
        return UserLLMConfig.objects.create(**validated_data)


class UserLLMConfigTestSerializer(_BaseSerializer):
    """Serializer for testing an LLM config without saving."""

    provider = serializers.CharField()
    model_name = serializers.CharField()
    api_key = serializers.CharField()
    base_url = serializers.CharField(required=False, default="")
