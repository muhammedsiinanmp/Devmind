from __future__ import annotations

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
            models.Index(fields=["completed_at"]),
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
    github_comment_id = models.BigIntegerField(
        null=True,
        blank=True,
        unique=True,
        help_text=(
            "ID of the inline review comment DevMind posted on GitHub. Null "
            "for comments that weren't posted inline (folded into the review "
            "body) or posted before this was recorded."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reviews_reviewcomment"
        ordering = ["file_path", "line_number"]
        indexes = [
            models.Index(fields=["review", "severity"]),
            models.Index(fields=["review", "file_path", "line_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.severity.upper()} {self.category} in {self.file_path}:{self.line_number}"


class CommentFeedback(models.Model):
    """
    A developer's verdict on one DevMind comment, from one source.

    Sources and what they mean (docs/feedback-learning.md):
    - reaction: 👍/👎 on the comment, counted when the PR closes. More 👍
      than 👎 is accepted, more 👎 than 👍 is rejected, a tie is no signal.
    - reply: a reply to the comment that starts with one of the phrases in
      services/feedback.py (for example "fixed" or "false positive").
    - resolved: the comment's thread was resolved (accepted). Unresolving it
      removes the row.

    One row per comment and source; a later event from the same source
    replaces it. When sources disagree, effective_signal() picks one.
    """

    SIGNAL_CHOICES = [
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
    ]

    SOURCE_CHOICES = [
        ("reaction", "Reaction"),
        ("reply", "Reply"),
        ("resolved", "Resolved thread"),
    ]

    # Explicit votes beat explicit words, which beat resolving a thread
    # (people also resolve threads to dismiss them).
    SOURCE_PRECEDENCE = ("reaction", "reply", "resolved")

    comment = models.ForeignKey(
        ReviewComment,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    signal = models.CharField(max_length=10, choices=SIGNAL_CHOICES)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    source_github_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text=(
            "For reply verdicts, the GitHub id of the reply that gave it, so "
            "deleting or editing that reply can remove it."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reviews_commentfeedback"
        ordering = ["comment_id", "source"]
        constraints = [
            models.UniqueConstraint(
                fields=["comment", "source"],
                name="uq_commentfeedback_comment_source",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.signal} ({self.source}) on comment #{self.comment_id}"

    @classmethod
    def effective(cls, rows) -> CommentFeedback | None:
        """
        The row that decides a comment's feedback state, or None.

        ``rows`` are one comment's feedback rows. The source that comes first
        in SOURCE_PRECEDENCE wins.
        """
        by_source = {row.source: row for row in rows}
        for source in cls.SOURCE_PRECEDENCE:
            if source in by_source:
                return by_source[source]
        return None


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
    diff_text = models.TextField(
        blank=True,
        default="",
        help_text="Raw unified diff stored at review time to avoid re-fetching from GitHub.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reviews_reviewrun"
        verbose_name_plural = "review runs"

    def __str__(self) -> str:
        return f"ReviewRun for Review #{self.review_id} ({self.model_used})"
