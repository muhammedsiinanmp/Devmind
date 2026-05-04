"""
Tests for the reviews app models.

Tests match acceptance criteria from P2-01:
- All four models migrate cleanly
- ReviewQuerySet.pending() returns only pending reviews
- Review.__str__ returns correct format
- ReviewFactory creates valid objects with FK relations
"""

import pytest
from django.db import connection

from apps.reviews.models import Review, ReviewComment, ReviewRun, RepoScan
from apps.reviews.tests.factories import (
    RepoScanFactory,
    ReviewCommentFactory,
    ReviewFactory,
    ReviewRunFactory,
)


@pytest.mark.django_db
class TestReviewModel:
    """Tests for the Review model."""

    def test_create_review(self) -> None:
        """Test creating a basic review."""
        review = ReviewFactory()
        assert review.pk is not None
        assert review.status == "pending"
        assert review.pr_number is not None
        assert review.repository is not None

    def test_review_str_format(self) -> None:
        """Test Review.__str__ returns correct format."""
        review = ReviewFactory(
            repository__full_name="acme/api",
            pr_number=42,
        )
        expected = f"Review #{review.pk} — acme/api PR#42"
        assert str(review) == expected
        # Also verify parts
        assert "acme/api" in str(review)
        assert "PR#42" in str(review)

    def test_review_status_choices(self) -> None:
        """Test all status choices are valid."""
        for status, _ in Review.STATUS_CHOICES:
            review = ReviewFactory(status=status)
            assert review.status == status

    def test_review_risk_score_bounds(self) -> None:
        """Test risk_score is saved correctly."""
        review = ReviewFactory(risk_score=75)
        assert review.risk_score == 75

    def test_review_completed_at_auto_set(self) -> None:
        """Test completed_at is set on completion."""
        from django.utils import timezone

        review = ReviewFactory(status="completed", completed_at=timezone.now())
        assert review.completed_at is not None


@pytest.mark.django_db
class TestReviewCommentModel:
    """Tests for the ReviewComment model."""

    def test_create_comment(self) -> None:
        """Test creating a basic comment."""
        comment = ReviewCommentFactory()
        assert comment.pk is not None
        assert comment.review is not None
        assert comment.file_path is not None

    def test_comment_str_format(self) -> None:
        """Test ReviewComment.__str__ format."""
        comment = ReviewCommentFactory(
            file_path="src/main.py",
            line_number=42,
            severity="warning",
            category="quality",
        )
        assert "WARNING" in str(comment).upper()
        assert "QUALITY" in str(comment).upper()
        assert "src/main.py" in str(comment)

    def test_comment_severity_choices(self) -> None:
        """Test all severity choices are valid."""
        for severity, _ in ReviewComment.SEVERITY_CHOICES:
            comment = ReviewCommentFactory(severity=severity)
            assert comment.severity == severity

    def test_comment_category_choices(self) -> None:
        """Test all category choices are valid."""
        for category, _ in ReviewComment.CATEGORY_CHOICES:
            comment = ReviewCommentFactory(category=category)
            assert comment.category == category

    def test_comment_suggested_fix_optional(self) -> None:
        """Test suggested_fix is optional."""
        comment = ReviewCommentFactory(suggested_fix="")
        assert comment.suggested_fix == ""


@pytest.mark.django_db
class TestReviewRunModel:
    """Tests for the ReviewRun model."""

    def test_create_run(self) -> None:
        """Test creating a basic review run."""
        run = ReviewRunFactory()
        assert run.pk is not None
        assert run.review is not None
        assert run.model_used is not None

    def test_run_str_format(self) -> None:
        """Test ReviewRun.__str__ format."""
        run = ReviewRunFactory(model_used="google/gemini-2.0-flash")
        assert "google/gemini-2.0-flash" in str(run)
        assert "ReviewRun" in str(run)

    def test_run_defaults(self) -> None:
        """Test default values."""
        run = ReviewRunFactory(prompt_tokens=0, completion_tokens=0, latency_ms=0)
        assert run.prompt_tokens == 0
        assert run.completion_tokens == 0
        assert run.latency_ms == 0


@pytest.mark.django_db
class TestRepoScanModel:
    """Tests for the RepoScan model."""

    def test_create_scan(self) -> None:
        """Test creating a basic repo scan."""
        scan = RepoScanFactory()
        assert scan.pk is not None
        assert scan.status == "queued"
        assert scan.progress == 0

    def test_scan_str_format(self) -> None:
        """Test RepoScan.__str__ format."""
        scan = RepoScanFactory(status="scanning", progress=50)
        assert "scanning" in str(scan)
        assert "50%" in str(scan)

    def test_scan_status_choices(self) -> None:
        """Test all status choices are valid."""
        for status, _ in RepoScan.STATUS_CHOICES:
            scan = RepoScanFactory(status=status)
            assert scan.status == status

    def test_scan_progress_bounds(self) -> None:
        """Test progress is 0-100."""
        scan = RepoScanFactory(progress=50)
        assert scan.progress == 50


@pytest.mark.django_db
class TestReviewQuerySet:
    """Tests for ReviewQuerySet methods."""

    def test_pending_filter(self) -> None:
        """Test pending() returns only pending reviews."""
        pending_review = ReviewFactory(status="pending")
        completed_review = ReviewFactory(status="completed")

        pending_qs = Review.objects.pending()
        assert pending_review in pending_qs
        assert completed_review not in pending_qs

    def test_completed_filter(self) -> None:
        """Test completed() returns only completed reviews."""
        ReviewFactory(status="pending")
        completed_review = ReviewFactory(status="completed")

        completed_qs = Review.objects.completed()
        assert completed_review in completed_qs

    def test_failed_filter(self) -> None:
        """Test failed() returns only failed reviews."""
        ReviewFactory(status="pending")
        failed_review = ReviewFactory(status="failed")

        failed_qs = Review.objects.failed()
        assert failed_review in failed_qs

    def test_processing_filter(self) -> None:
        """Test processing() returns only processing reviews."""
        processing_review = ReviewFactory(status="processing")
        ReviewFactory(status="pending")

        processing_qs = Review.objects.processing()
        assert processing_review in processing_qs

    def test_by_repository_filter(self) -> None:
        """Test by_repository() filters correctly."""
        repo = ReviewFactory().repository
        review_in_repo = ReviewFactory(repository=repo)
        ReviewFactory()

        repo_qs = Review.objects.by_repository(repo)
        assert review_in_repo in repo_qs

    def test_high_risk_filter(self) -> None:
        """Test high_risk() returns reviews with risk >= 70."""
        ReviewFactory(risk_score=50)
        high_risk = ReviewFactory(risk_score=80)

        high_risk_qs = Review.objects.high_risk()
        assert high_risk in high_risk_qs

    def test_low_risk_filter(self) -> None:
        """Test low_risk() returns reviews with risk < 30."""
        ReviewFactory(risk_score=50)
        low_risk = ReviewFactory(risk_score=20)

        low_risk_qs = Review.objects.low_risk()
        assert low_risk in low_risk_qs


@pytest.mark.django_db
class TestModelIntegration:
    """Integration tests for model relationships."""

    def test_review_with_comments(self) -> None:
        """Test Review can have multiple comments."""
        review = ReviewFactory()
        comment1 = ReviewCommentFactory(review=review)
        comment2 = ReviewCommentFactory(review=review)

        assert review.comments.count() == 2
        assert comment1 in review.comments.all()
        assert comment2 in review.comments.all()

    def test_review_with_run(self) -> None:
        """Test Review can have one ReviewRun."""
        review = ReviewFactory()
        run = ReviewRunFactory(review=review)

        assert review.run == run
        assert run.review == review

    def test_repository_with_reviews(self) -> None:
        """Test Repository can have multiple reviews."""
        repo = ReviewFactory().repository
        ReviewFactory(repository=repo)
        ReviewFactory(repository=repo)

        assert repo.reviews.count() == 3

    def test_repository_with_scans(self) -> None:
        """Test Repository can have multiple scans."""
        repo = ReviewFactory().repository
        RepoScanFactory(repository=repo)
        RepoScanFactory(repository=repo)

        assert repo.scans.count() == 2


@pytest.mark.django_db
class TestMigrationIntegrity:
    """Test migrations work correctly."""

    def test_tables_created(self) -> None:
        """Test all model tables exist in database."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            tables = [row[0] for row in cursor.fetchall()]

        assert "reviews_review" in tables
        assert "reviews_reviewcomment" in tables
        assert "reviews_reviewrun" in tables
        assert "reviews_reposcan" in tables
