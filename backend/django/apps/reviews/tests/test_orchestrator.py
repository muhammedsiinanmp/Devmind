"""
Tests for Review Orchestrator.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, override_settings
from django.db import transaction

from apps.reviews.models import Review, ReviewComment, ReviewRun
from apps.reviews.tests.factories import ReviewFactory
from apps.repositories.tests.factories import UserFactory
from apps.reviews.services.orchestrator import (
    ReviewOrchestrator,
    ReviewAlreadyProcessingError,
    FastAPIError,
    ReviewResult,
    trigger_review_task,
)


class TestReviewResult:
    def test_review_result_creation(self):
        result = ReviewResult(
            repo_full_name="owner/repo",
            pr_number=1,
            comments=[{"file_path": "app.py", "severity": "warning"}],
            risk_score=25,
            model_used="google/gemini",
            provider="google",
            latency_ms=1500,
        )
        assert result.repo_full_name == "owner/repo"
        assert result.risk_score == 25


class TestReviewOrchestratorInit:
    def test_orchestrator_sets_attributes(self):
        review = Mock(spec=Review)
        review.repository.full_name = "owner/repo"

        orchestrator = ReviewOrchestrator(review)

        assert orchestrator.review == review
        assert hasattr(orchestrator, "fastapi_url")


class TestStatusTransitions:
    @pytest.mark.django_db
    def test_pending_to_processing_transition(self):
        """Test pending → processing status transition."""
        review = ReviewFactory(status="pending")

        with patch.object(
            ReviewOrchestrator, "_call_fastapi"
        ) as mock_call, patch.object(ReviewOrchestrator, "_fetch_diff") as mock_diff:
            mock_diff.return_value = "dummy diff"
            mock_call.return_value = ReviewResult(
                repo_full_name="owner/repo",
                pr_number=1,
                comments=[],
                risk_score=0,
            )

            orchestrator = ReviewOrchestrator(review)
            orchestrator.run()

            review.refresh_from_db()
            assert review.status == "completed"


class TestAlreadyProcessingError:
    def test_error_raised_when_processing(self):
        review = Mock()
        review.status = "processing"

        orchestrator = ReviewOrchestrator(review)

        with pytest.raises(ReviewAlreadyProcessingError):
            orchestrator.run()

    def test_error_raised_when_completed(self):
        review = Mock()
        review.status = "completed"

        orchestrator = ReviewOrchestrator(review)

        with pytest.raises(FastAPIError):
            orchestrator.run()


class TestFastAPICall:
    @pytest.mark.django_db
    def test_call_fastapi_success(self):
        review = MagicMock()
        review.repository.full_name = "owner/repo"
        review.pr_number = 1

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "repo_full_name": "owner/repo",
                "pr_number": 1,
                "comments": [
                    {
                        "file_path": "app.py",
                        "line_number": 10,
                        "category": "security",
                        "severity": "warning",
                        "body": "Good",
                    }
                ],
                "risk_score": 10,
                "model_used": "google/gemini",
                "provider": "google",
                "latency_ms": 1000,
            }

            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )

            orchestrator = ReviewOrchestrator(review)
            result = orchestrator._call_fastapi("test diff")

            assert result.risk_score == 10
            assert len(result.comments) == 1

    @pytest.mark.django_db
    def test_call_fastapi_503_error(self):
        review = MagicMock()
        review.repository.full_name = "owner/repo"

        with patch("httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 503

            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )

            orchestrator = ReviewOrchestrator(review)

            with pytest.raises(FastAPIError):
                orchestrator._call_fastapi("test diff")


class TestSummaryBuilding:
    def test_build_summary_with_critical(self):
        review = MagicMock()
        orchestrator = ReviewOrchestrator(review)

        comments = [
            {"severity": "critical"},
            {"severity": "critical"},
            {"severity": "error"},
            {"severity": "warning"},
        ]

        summary = orchestrator._build_summary(comments)

        assert "2 critical" in summary
        assert "1 error" in summary
        assert "1 warning" in summary

    def test_build_summary_empty(self):
        review = MagicMock()
        orchestrator = ReviewOrchestrator(review)

        summary = orchestrator._build_summary([])

        assert summary == "No issues found."


class TestTriggerTask:
    @pytest.mark.django_db
    def test_trigger_review_task(self):
        review = ReviewFactory(status="pending")

        with patch.object(ReviewOrchestrator, "run") as mock_run:
            mock_run.return_value = ReviewResult(
                repo_full_name="owner/repo",
                pr_number=2,
            )

            trigger_review_task(review.pk)

            mock_run.assert_called_once()


class TestOrchestratorIntegration:
    @pytest.mark.django_db
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_full_pipeline_status_transition(self):
        """Test complete pipeline: pending → processing → completed"""
        review = ReviewFactory(status="pending")

        with patch.object(
            ReviewOrchestrator, "_call_fastapi"
        ) as mock_call, patch.object(ReviewOrchestrator, "_fetch_diff") as mock_diff:
            mock_diff.return_value = "dummy diff"
            mock_call.return_value = ReviewResult(
                repo_full_name="owner/repo",
                pr_number=3,
                comments=[],
                risk_score=0,
            )

            orchestrator = ReviewOrchestrator(review)
            result = orchestrator.run()

            review.refresh_from_db()
            assert review.status == "completed"
            assert result is not None
