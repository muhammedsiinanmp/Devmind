from django.contrib import admin
from django.db.models import QuerySet
from django.utils.html import format_html

from apps.reviews.models import RepoScan, Review, ReviewComment, ReviewRun


class ReviewCommentInline(admin.TabularInline):
    """Inline for ReviewComment - read-only."""

    model = ReviewComment
    extra = 0
    readonly_fields = [
        "file_path",
        "line_number",
        "body",
        "severity",
        "category",
        "suggested_fix",
        "created_at",
    ]
    can_delete = False

    def has_add_permission(self, request, obj):
        return False


class ReviewRunInline(admin.TabularInline):
    """Inline for ReviewRun - read-only."""

    model = ReviewRun
    extra = 0
    readonly_fields = [
        "agent_iterations",
        "model_used",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "created_at",
    ]
    can_delete = False

    def has_add_permission(self, request, obj):
        return False


@admin.display(description="Risk Score", ordering="risk_score")
def risk_score_display(obj: Review) -> str:
    """Display risk score as color-coded badge."""
    if obj.risk_score is None:
        return format_html('<span style="color: #6c757d;">—</span>')

    if obj.risk_score <= 30:
        color = "#28a745"  # green
    elif obj.risk_score <= 70:
        color = "#ffc107"  # yellow
    else:
        color = "#dc3545"  # red

    return format_html(
        '<span style="background-color: {}; color: white; padding: 2px 8px; '
        'border-radius: 4px; font-weight: bold;">{}</span>',
        color,
        obj.risk_score,
    )


@admin.display(description="Status")
def status_badge(obj: Review) -> str:
    """Display status as colored badge."""
    colors = {
        "pending": "#6c757d",
        "processing": "#17a2b8",
        "completed": "#28a745",
        "failed": "#dc3545",
    }
    color = colors.get(obj.status, "#6c757d")
    return format_html(
        '<span style="background-color: {}; color: white; padding: 2px 8px; '
        'border-radius: 4px;">{}</span>',
        color,
        obj.get_status_display(),
    )


class ReviewAdmin(admin.ModelAdmin):
    """Admin for Review model."""

    list_display = [
        "id",
        "repository",
        "pr_number",
        "status",
        "risk_score",
        "created_at",
    ]
    list_filter = ["status", "repository__language"]
    search_fields = ["repository__full_name", "pr_title"]
    readonly_fields = [
        "id",
        "repository",
        "pr_number",
        "pr_title",
        "head_sha",
        "base_sha",
        "diff_url",
        "created_at",
        "completed_at",
    ]
    inlines = [ReviewCommentInline, ReviewRunInline]
    ordering = ["-created_at"]

    @admin.display(description="Risk Score", ordering="risk_score")
    def risk_score_display(self, obj: Review) -> str:
        if obj.risk_score is None:
            return format_html('<span style="color: #6c757d;">—</span>')

        if obj.risk_score <= 30:
            color = "#28a745"
        elif obj.risk_score <= 70:
            color = "#ffc107"
        else:
            color = "#dc3545"

        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px; font-weight: bold;">{}</span>',
            color,
            obj.risk_score,
        )

    @admin.display(description="Status")
    def status_badge(self, obj: Review) -> str:
        colors = {
            "pending": "#6c757d",
            "processing": "#17a2b8",
            "completed": "#28a745",
            "failed": "#dc3545",
        }
        color = colors.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; '
            'border-radius: 4px;">{}</span>',
            color,
            obj.get_status_display(),
        )

    fieldsets = [
        (
            "Review Details",
            {
                "fields": [
                    "repository",
                    "pr_number",
                    "pr_title",
                    "status",
                    "risk_score",
                    "summary",
                ]
            },
        ),
        (
            "Git Information",
            {
                "fields": ["head_sha", "base_sha", "diff_url"],
                "classes": ["collapse"],
            },
        ),
        (
            "Timestamps",
            {
                "fields": ["created_at", "completed_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    def get_readonly_fields(self, request, obj: Review | None = None) -> list[str]:
        if obj and obj.status in ["completed", "failed"]:
            return list(super().get_readonly_fields(request, obj))
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None) -> bool:
        return True


class RepoScanAdmin(admin.ModelAdmin):
    """Admin for RepoScan model."""

    list_display = [
        "id",
        "repository",
        "triggered_by",
        "status",
        "progress_bar",
        "created_at",
    ]
    list_filter = ["status"]
    search_fields = ["repository__full_name"]
    readonly_fields = [
        "id",
        "repository",
        "triggered_by",
        "status",
        "progress",
        "total_files",
        "files_scanned",
        "total_issues",
        "critical_count",
        "warning_count",
        "info_count",
        "scan_duration_ms",
        "created_at",
        "completed_at",
    ]
    ordering = ["-created_at"]

    @admin.display(description="Progress")
    def progress_bar(self, obj: RepoScan) -> str:
        """Display progress as progress bar."""
        if obj.total_files == 0:
            return format_html("0%")

        return format_html(
            '<div style="width: 100px; background-color: #e9ecef; '
            'border-radius: 4px; overflow: hidden;">'
            '<div style="width: {}%; background-color: #28a745; '
            'height: 20px; text-align: center; color: white; font-size: 12px;">'
            "{}%"
            "</div></div>",
            obj.progress,
            obj.progress,
        )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        if obj is None:
            return True
        return obj.status != "completed"


admin.site.register(Review, ReviewAdmin)
admin.site.register(RepoScan, RepoScanAdmin)
