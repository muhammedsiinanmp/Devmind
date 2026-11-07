from rest_framework import serializers

from apps.reviews.models import CommentFeedback, Review, ReviewComment, ReviewRun


class CommentFeedbackStateSerializer(serializers.Serializer):
    """A comment's effective feedback verdict and the source that decided it."""

    signal = serializers.ChoiceField(choices=CommentFeedback.SIGNAL_CHOICES)
    source = serializers.ChoiceField(choices=CommentFeedback.SOURCE_CHOICES)
    updated_at = serializers.DateTimeField()


class ReviewCommentSerializer(serializers.ModelSerializer):
    """Serializer for ReviewComment model."""

    feedback = serializers.SerializerMethodField()

    class Meta:
        model = ReviewComment
        fields = [
            "id",
            "file_path",
            "line_number",
            "body",
            "severity",
            "category",
            "suggested_fix",
            "created_at",
            "feedback",
        ]
        read_only_fields = fields

    def get_feedback(self, obj: ReviewComment) -> dict | None:
        """Null when developers gave no verdict on the comment."""
        row = CommentFeedback.effective(obj.feedback.all())
        return CommentFeedbackStateSerializer(row).data if row else None


class ReviewRunSerializer(serializers.ModelSerializer):
    """Serializer for ReviewRun model."""

    class Meta:
        model = ReviewRun
        fields = [
            "id",
            "agent_iterations",
            "model_used",
            "prompt_tokens",
            "completion_tokens",
            "latency_ms",
            "diff_text",
            "created_at",
        ]
        read_only_fields = fields


class ReviewSerializer(serializers.ModelSerializer):
    """
    Full Review serializer with nested comments and run.
    Comments are read-only through this endpoint.
    """

    comments = ReviewCommentSerializer(many=True, read_only=True)
    run = ReviewRunSerializer(read_only=True)
    repository_name = serializers.CharField(
        source="repository.full_name", read_only=True
    )

    class Meta:
        model = Review
        fields = [
            "id",
            "repository",
            "repository_name",
            "pr_number",
            "pr_title",
            "head_sha",
            "base_sha",
            "diff_url",
            "status",
            "risk_score",
            "summary",
            "created_at",
            "completed_at",
            "comments",
            "run",
        ]
        read_only_fields = ["id", "created_at", "completed_at"]


class ReviewListSerializer(serializers.ModelSerializer):
    """
    Lightweight Review serializer for list endpoint.
    No nested comments to reduce payload size.
    """

    repository_name = serializers.CharField(
        source="repository.full_name", read_only=True
    )

    class Meta:
        model = Review
        fields = [
            "id",
            "repository",
            "repository_name",
            "pr_number",
            "pr_title",
            "head_sha",
            "status",
            "risk_score",
            "created_at",
            "completed_at",
        ]
        read_only_fields = ["id", "created_at", "completed_at"]
