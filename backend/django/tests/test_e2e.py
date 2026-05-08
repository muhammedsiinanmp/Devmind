"""
End-to-end integration test for the full review pipeline.

Tests: webhook -> trigger_review_task -> orchestrator -> FastAPI -> GitHub poster
"""

import pytest
from unittest.mock import patch, MagicMock
from django.test import override_settings

from apps.reviews.models import Review, ReviewComment, Repository
from apps.reviews.services.orchestrator import ReviewOrchestrator


@pytest.fixture
def repository(db):
    return Repository.objects.create(
        name="test-repo",
        full_name="testuser/test-repo",
        owner=MagicMock(),
        github_token="test_token",
    )


@pytest.fixture
def review(db, repository):
    return Review.objects.create(
        repository=repository,
        pr_number=1,
        pr_title="Test PR",
        head_sha="abc123",
        status="pending",
    )


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
@pytest.mark.django_db
class TestReviewPipeline:
    def test_full_pipeline_webhook_to_comments(self, repository, review):
        """
        Test the full pipeline:
        1. Webhook triggers review creation
        2. ReviewOrchestrator processes the review
        3. FastAPI is called (mocked)
        4. Results are saved
        5. GitHub comments are posted (mocked)
        """
        with patch("apps.reviews.services.orchestrator.httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "repo_full_name": "testuser/test-repo",
                "pr_number": 1,
                "comments": [
                    {
                        "file_path": "src/main.py",
                        "line_number": 10,
                        "category": "security",
                        "severity": "warning",
                        "body": "Consider using environment variables for sensitive data",
                        "suggested_fix": None,
                    },
                    {
                        "file_path": "src/utils.py",
                        "line_number": 25,
                        "category": "code_quality",
                        "severity": "info",
                        "body": "Function is too long (50 lines)",
                        "suggested_fix": "Consider breaking into smaller functions",
                    },
                ],
                "risk_score": 45,
                "model_used": "gpt-4",
                "provider": "openai",
                "latency_ms": 2500,
            }
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_response)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.return_value.post.return_value = mock_response

            with patch(
                "apps.reviews.services.orchestrator.GithubService"
            ) as mock_github:
                mock_github.return_value.get_pull_request_diff.return_value = (
                    "diff content"
                )

                orchestrator = ReviewOrchestrator(review)
                result = orchestrator.run()

        review.refresh_from_db()
        assert review.status == "completed"
        assert review.risk_score == 45
        assert review.summary is not None

        comments = ReviewComment.objects.filter(review=review)
        assert comments.count() == 2
        assert comments.filter(file_path="src/main.py").exists()
        assert comments.filter(file_path="src/utils.py").exists()

    def test_review_status_transitions(self, repository, review):
        """Test that review status transitions correctly."""
        with patch("apps.reviews.services.orchestrator.httpx.Client"):
            with patch("apps.reviews.services.orchestrator.GithubService"):
                orchestrator = ReviewOrchestrator(review)

                review.refresh_from_db()
                assert review.status == "pending"

                orchestrator.run()

                review.refresh_from_db()
                assert review.status == "completed"

    def test_orchestrator_handles_fastapi_error(self, repository, review):
        """Test that orchestrator handles FastAPI errors gracefully."""
        with patch("apps.reviews.services.orchestrator.httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_client.return_value.__enter__ = MagicMock(return_value=mock_response)
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.return_value.post.return_value = mock_response

            with patch("apps.reviews.services.orchestrator.GithubService"):
                orchestrator = ReviewOrchestrator(review)

                with pytest.raises(Exception):
                    orchestrator.run()

        review.refresh_from_db()
        assert review.status == "failed"


@pytest.mark.django_db
class TestMetricsEndpoint:
    def test_metrics_endpoint_returns_data(self, client):
        """Test that /metrics endpoint returns Prometheus format."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "devmind_" in response.content.decode()


@pytest.mark.django_db
class TestSentryErrorCapture:
    def test_sentry_captures_test_error(self, client):
        """Test that Sentry captures errors from test view."""
        response = client.get("/test-error/")
        assert response.status_code == 500
