from django.contrib import admin
from django.utils.safestring import mark_safe

from apps.repositories.models import Repository
from apps.repositories.tasks import install_webhook_task, remove_webhook_task


@admin.action(description="Install GitHub webhooks for selected repositories")
def install_webhooks_action(
    modeladmin: admin.ModelAdmin, request: object, queryset: object
) -> None:  # type: ignore[type-arg]
    for repo in queryset.filter(webhook_id__isnull=True):  # type: ignore[union-attr]
        install_webhook_task.delay(repo_id=repo.pk)


@admin.action(description="Remove GitHub webhooks from selected repositories")
def remove_webhooks_action(
    modeladmin: admin.ModelAdmin, request: object, queryset: object
) -> None:  # type: ignore[type-arg]
    for repo in queryset.exclude(webhook_id__isnull=True):  # type: ignore[union-attr]
        remove_webhook_task.delay(repo_id=repo.pk)


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = [
        "full_name",
        "owner",
        "language",
        "is_active",
        "review_enabled",
        "webhook_status",
        "last_synced_at",
        "created_at",
    ]
    list_filter = ["is_active", "review_enabled", "language", "is_private"]
    search_fields = ["full_name", "owner__email", "owner__github_login"]
    readonly_fields = [
        "github_id",
        "full_name",
        "html_url",
        "webhook_id",
        "last_synced_at",
        "created_at",
        "updated_at",
    ]
    actions = [install_webhooks_action, remove_webhooks_action]
    ordering = ["-created_at"]
    list_per_page = 50

    def webhook_status(self, obj: Repository) -> str:
        if obj and obj.webhook_id:
            return mark_safe('<span style="color: green;">✓ Installed (' + str(obj.webhook_id) + ')</span>')
        return mark_safe('<span style="color: orange;">✗ Not installed</span>')

    webhook_status.short_description = "Webhook"  # type: ignore[attr-defined]
