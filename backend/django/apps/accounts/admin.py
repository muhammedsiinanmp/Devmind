from typing import TYPE_CHECKING

from django.contrib import admin

from apps.accounts.models import CustomUser, GithubToken

if TYPE_CHECKING:
    _BaseCustomUserAdmin = admin.ModelAdmin[CustomUser]
    _BaseGithubTokenAdmin = admin.ModelAdmin[GithubToken]
else:
    _BaseCustomUserAdmin = admin.ModelAdmin
    _BaseGithubTokenAdmin = admin.ModelAdmin


@admin.register(CustomUser)
class CustomUserAdmin(_BaseCustomUserAdmin):
    """Admin interface for CustomUser."""

    list_display = (
        "email",
        "github_login",
        "is_active",
        "is_staff",
        "created_at",
    )
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "github_login")
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "GitHub",
            {"fields": ("github_id", "github_login", "avatar_url")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )


@admin.register(GithubToken)
class GithubTokenAdmin(_BaseGithubTokenAdmin):
    """Admin interface for GithubToken — token is masked for security."""

    list_display = ("user", "token_type", "masked_token", "created_at")
    raw_id_fields = ("user",)
    exclude = ("access_token",)  # Never show the raw encrypted field

    @admin.display(description="Access Token")
    def masked_token(self, obj: GithubToken) -> str:
        """Display only the last 4 characters of the token."""
        token = obj.access_token
        if token and len(token) > 4:
            return f"gho_***{token[-4:]}"
        return "***"
