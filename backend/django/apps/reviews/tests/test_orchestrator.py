"""
Tests for Review Orchestrator.
"""

import httpx
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import override_settings

from apps.reviews.models import Review
from apps.reviews.tests.factories import ReviewFactory
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

        with (
            patch.object(ReviewOrchestrator, "_call_fastapi") as mock_call,
            patch.object(ReviewOrchestrator, "_fetch_diff") as mock_diff,
        ):
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
    def test_call_fastapi_503_error(self, no_retry_wait):
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


class TestFetchDiff:
    @pytest.mark.django_db
    def test_fetch_diff_uses_github_service(self):
        review = ReviewFactory(status="pending")
        orchestrator = ReviewOrchestrator(review)

        with patch("apps.repositories.services.GitHubService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_pull_request_diff.return_value = "diff --git a b"

            diff = orchestrator._fetch_diff()

            assert diff == "diff --git a b"
            mock_service_cls.assert_called_once_with(
                access_token=review.repository.owner.github_token.access_token,
                user=review.repository.owner,
            )
            mock_service.get_pull_request_diff.assert_called_once_with(
                repo_full_name=review.repository.full_name,
                pr_number=review.pr_number,
            )


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

        with (
            patch.object(ReviewOrchestrator, "_call_fastapi") as mock_call,
            patch.object(ReviewOrchestrator, "_fetch_diff") as mock_diff,
        ):
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


@pytest.fixture
def no_retry_wait():
    """Skip tenacity's back-off sleeps; attempts are still counted."""
    with patch.object(
        ReviewOrchestrator._attempt_fastapi_call.retry, "sleep", lambda seconds: None
    ):
        yield


def _orchestrator_with_client(mock_client) -> tuple[ReviewOrchestrator, MagicMock]:
    review = MagicMock()
    review.repository.full_name = "owner/repo"
    review.pk = 1
    post = mock_client.return_value.__enter__.return_value.post
    return ReviewOrchestrator(review), post


def _ok_response():
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "repo_full_name": "owner/repo",
        "pr_number": 1,
        "comments": [],
        "risk_score": 0,
        "files_reviewed": ["app.py"],
        "files_skipped": [],
    }
    return response


class TestFastAPIRetryPolicy:
    def test_read_timeout_is_not_retried(self, no_retry_wait):
        with patch("httpx.Client") as mock_client:
            orchestrator, post = _orchestrator_with_client(mock_client)
            post.side_effect = httpx.ReadTimeout("read timed out")

            with pytest.raises(FastAPIError, match="may still be running"):
                orchestrator._call_fastapi("diff")

        assert post.call_count == 1

    def test_connect_error_is_retried_then_succeeds(self, no_retry_wait):
        with patch("httpx.Client") as mock_client:
            orchestrator, post = _orchestrator_with_client(mock_client)
            post.side_effect = [httpx.ConnectError("refused"), _ok_response()]

            result = orchestrator._call_fastapi("diff")

        assert post.call_count == 2
        assert result.files_reviewed == ["app.py"]

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    def test_429_and_5xx_are_retried_three_times(self, no_retry_wait, status_code):
        with patch("httpx.Client") as mock_client:
            orchestrator, post = _orchestrator_with_client(mock_client)
            post.return_value = MagicMock(status_code=status_code)

            with pytest.raises(FastAPIError, match="after 3 attempts"):
                orchestrator._call_fastapi("diff")

        assert post.call_count == 3

    @pytest.mark.parametrize("status_code", [400, 403, 422])
    def test_other_errors_are_not_retried(self, no_retry_wait, status_code):
        with patch("httpx.Client") as mock_client:
            orchestrator, post = _orchestrator_with_client(mock_client)
            post.return_value = MagicMock(status_code=status_code, text="no")

            with pytest.raises(FastAPIError):
                orchestrator._call_fastapi("diff")

        assert post.call_count == 1


class TestTimeoutCheck:
    def test_default_timeout_is_above_the_review_deadline(self):
        from apps.reviews.checks import check_fastapi_timeout_exceeds_review_deadline

        assert check_fastapi_timeout_exceeds_review_deadline(None) == []

    @override_settings(FASTAPI_TIMEOUT_SECONDS=60, REVIEW_DEADLINE_SECONDS=100)
    def test_warns_when_timeout_is_not_above_the_deadline(self):
        from django.core.checks import run_checks

        warnings = [w for w in run_checks() if w.id == "reviews.W001"]

        assert len(warnings) == 1
        assert "FASTAPI_TIMEOUT_SECONDS (60)" in warnings[0].msg
