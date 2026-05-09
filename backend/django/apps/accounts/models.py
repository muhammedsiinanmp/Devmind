from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.accounts.encryption import EncryptedCharField
from apps.accounts.managers import CustomUserManager


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model using email as the primary identifier.
    Linked to GitHub via github_id for OAuth authentication.
    """

    email = models.EmailField(unique=True)
    github_id = models.BigIntegerField(unique=True, null=True, blank=True)
    github_login = models.CharField(max_length=255, blank=True, default="")
    avatar_url = models.URLField(max_length=500, blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "accounts_customuser"

    def __str__(self) -> str:
        return self.email


class GithubToken(models.Model):
    """
    Stores encrypted GitHub OAuth access tokens.
    One-to-one relationship with CustomUser. The access_token field
    is encrypted at rest using Fernet symmetric encryption.
    """

    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="github_token",
    )
    access_token = EncryptedCharField(max_length=500)
    token_type = models.CharField(max_length=50, default="bearer")
    scopes = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_githubtoken"

    def __str__(self) -> str:
        return f"GithubToken for {self.user.email}"


class UserLLMConfig(models.Model):
    """
    Stores user's own LLM API keys for BYOK (Bring Your Own Key).
    Keys are encrypted at rest using Fernet symmetric encryption.
    """

    PROVIDER_CHOICES = [
        ("openai", "OpenAI"),
        ("anthropic", "Anthropic"),
        ("google_vertex", "Google Vertex AI"),
        ("mistral", "Mistral"),
        ("custom", "Custom OpenAI-compatible"),
    ]

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="llm_configs",
    )
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES)
    model_name = models.CharField(max_length=100)
    api_key = EncryptedCharField(max_length=500)
    base_url = models.URLField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_userllmconfig"
        ordering = ["priority", "-created_at"]
        unique_together = ["user", "provider", "model_name"]

    def __str__(self) -> str:
        return f"{self.provider}/{self.model_name} for {self.user.email}"

    @property
    def masked_key(self) -> str:
        """Return masked version of API key for display."""
        key = self.api_key
        if len(key) <= 10:
            return "***"
        return f"{key[:7]}***{key[-4:]}"
