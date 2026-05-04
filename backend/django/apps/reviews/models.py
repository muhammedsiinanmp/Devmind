from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.reviews.managers import ReviewQuerySet


class Review(models.Model):
    """
    Represents a code review for a GitHub pull request.

    Status machine: pending → processing → completed | failed
    - pending: Awaiting processing
    - processing: Currently being reviewed by the AI agent
    - completed: Review finished with comments posted
    - failed: Review failed (check summary for error details)
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    pr_number = models.IntegerField(
        help_text="GitHub pull request number.",
    )
    pr_title = models.CharField(
        max_length=500,
        help_text="Pull request title from GitHub.",
    )
    head_sha = models.CharField(
        max_length=40,
        help_text="SHA of the head commit being reviewed.",
    )
    base_sha = models.CharField(
        max_length=40,
        help_text="SHA of the base commit.",
    )
    diff_url = models.URLField(
        max_length=500,
        help_text="URL to view the diff on GitHub.",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
    )
    risk_score = models.IntegerField(
        null=True,
        blank=True,
        help_text="AI-calculated risk score from 0-100.",
    )
    summary = models.TextField(
        blank=True,
        default="",
        help_text="AI-generated summary of the review.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    objects = ReviewQuerySet.as_manager()

    class Meta:
        db_table = "reviews_review"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["repository", "pr_number"]),
        ]

    def __str__(self) -> str:
        return f"Review #{self.pk} — {self.repository.full_name} PR#{self.pr_number}"


class ReviewComment(models.Model):
    """
    An AI-generated comment on a specific file and line in a PR diff.

    Severity levels:
    - info: Informational, no action needed
    - warning: Should be addressed, not critical
    - error: Should be fixed, affects functionality
    - critical: Must be fixed before merge

    Categories:
    - security: Security vulnerability
    - quality: Code quality/style
    - tests: Missing or inadequate tests
    - style: Linting/formatting
    - performance: Performance concern
    """

    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("error", "Error"),
        ("critical", "Critical"),
    ]

    CATEGORY_CHOICES = [
        ("security", "Security"),
        ("quality", "Quality"),
        ("tests", "Tests"),
        ("style", "Style"),
        ("performance", "Performance"),
    ]

    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    file_path = models.CharField(
        max_length=500,
        help_text="File path relative to repository root.",
    )
    line_number = models.IntegerField(
        help_text="Line number in the diff.",
    )
    body = models.TextField(
        help_text="Comment body/description.",
    )
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
    )
    suggested_fix = models.TextField(
        blank=True,
        default="",
        help_text="Suggested code fix in diff format.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reviews_reviewcomment"
        ordering = ["file_path", "line_number"]

    def __str__(self) -> str:
        return f"{self.severity.upper()} {self.category} in {self.file_path}:{self.line_number}"


class ReviewRun(models.Model):
    """
    Tracks metadata about a single review execution.
    One-to-one with Review - created after review completes.
    """

    review = models.OneToOneField(
        Review,
        on_delete=models.CASCADE,
        related_name="run",
    )
    agent_iterations = models.IntegerField(
        default=0,
        help_text="Number of agent retry iterations.",
    )
    model_used = models.CharField(
        max_length=100,
        help_text="LLM model that generated the review (e.g. google/gemini-2.0-flash).",
    )
    prompt_tokens = models.IntegerField(
        default=0,
        help_text="Number of tokens in the prompt.",
    )
    completion_tokens = models.IntegerField(
        default=0,
        help_text="Number of tokens in the completion.",
    )
    latency_ms = models.IntegerField(
        default=0,
        help_text="LLM response time in milliseconds.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reviews_reviewrun"
        verbose_name_plural = "review runs"

    def __str__(self) -> str:
        return f"ReviewRun for Review #{self.review_id} ({self.model_used})"


class RepoScan(models.Model):
    """
    Represents a full repository scan for code issues.

    Status:
    - queued: Waiting to be processed
    - scanning: Currently scanning files
    - completed: Scan finished
    - failed: Scan failed (check summary for error)
    """

    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("scanning", "Scanning"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    repository = models.ForeignKey(
        "repositories.Repository",
        on_delete=models.CASCADE,
        related_name="scans",
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="repo_scans",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="queued",
        db_index=True,
    )
    progress = models.IntegerField(
        default=0,
        help_text="Scan progress percentage 0-100.",
    )
    total_files = models.IntegerField(
        default=0,
        help_text="Total number of files to scan.",
    )
    files_scanned = models.IntegerField(
        default=0,
        help_text="Number of files scanned so far.",
    )
    total_issues = models.IntegerField(
        default=0,
        help_text="Total issues found.",
    )
    critical_count = models.IntegerField(default=0)
    warning_count = models.IntegerField(default=0)
    info_count = models.IntegerField(default=0)
    scan_duration_ms = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reviews_reposcan"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"RepoScan #{self.pk} ({self.status}) - {self.progress}%"

    def save(self, *args, **kwargs) -> None:
        if self.completed_at and self.created_at:
            self.scan_duration_ms = int(
                (self.completed_at - self.created_at).total_seconds() * 1000
            )
        super().save(*args, **kwargs)
