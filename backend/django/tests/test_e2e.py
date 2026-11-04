"""
End-to-end test of the review pipeline inside Django.

Runs the real ReviewOrchestrator (status machine, FastAPI response parsing,
result persistence). Only the network boundaries are mocked: GitHub
(GitHubService) and FastAPI (httpx.Client).
"""

from unittest.mock import MagicMock, patch

import pytest

from apps.repositories.tests.factories import RepositoryFactory
from apps.reviews.models import ReviewComment
from apps.reviews.services.orchestrator import ReviewOrchestrator
from apps.reviews.tests.factories import ReviewFactory

FASTAPI_REVIEW_RESPONSE = {
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
            "category": "quality",
            "severity": "info",
            "body": "Function is too long (50 lines)",
            "suggested_fix": "Consider breaking into smaller functions",
        },
    ],
    "risk_score": 45,
    "model_used": "gemini-2.0-flash",
    "provider": "google",
    "latency_ms": 2500,
}


@pytest.fixture
def review(db):
    # RepositoryFactory's owner comes with a GitHub token
    repository = RepositoryFactory(full_name="testuser/test-repo")
    return ReviewFactory(repository=repository, pr_number=1, status="pending")


def _fastapi_client(mock_client_cls, status_code, payload=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload or {}
    response.text = ""
    client = mock_client_cls.return_value.__enter__.return_value
    client.post.return_value = response
    return client


@pytest.mark.django_db
class TestReviewPipeline:
    def test_full_pipeline_saves_comments_and_completes(self, review):
        with (
            patch("apps.reviews.services.orchestrator.httpx.Client") as mock_client,
            patch("apps.repositories.services.GitHubService") as mock_github,
            patch.object(ReviewOrchestrator, "_trigger_github_post"),
        ):
            fastapi = _fastapi_client(mock_client, 200, FASTAPI_REVIEW_RESPONSE)
            mock_github.return_value.get_pull_request_diff.return_value = "diff"

            ReviewOrchestrator(review).run()

        review.refresh_from_db()
        assert review.status == "completed"
        assert review.risk_score == 45
        assert review.summary
        assert review.completed_at is not None

        comments = ReviewComment.objects.filter(review=review)
        assert comments.count() == 2
        assert comments.filter(file_path="src/main.py", line_number=10).exists()
        assert comments.filter(file_path="src/utils.py", line_number=25).exists()

        # The diff from GitHub is what gets sent to FastAPI, with the secret
        sent = fastapi.post.call_args
        assert sent.kwargs["json"]["diff"] == "diff"
        assert sent.kwargs["headers"]["X-Internal-Secret"]

    def test_fastapi_error_marks_review_failed(self, review):
        with (
            patch("apps.reviews.services.orchestrator.httpx.Client") as mock_client,
            patch("apps.repositories.services.GitHubService") as mock_github,
        ):
            _fastapi_client(mock_client, 500)
            mock_github.return_value.get_pull_request_diff.return_value = "diff"

            with pytest.raises(Exception):
                ReviewOrchestrator(review).run()

        review.refresh_from_db()
        assert review.status == "failed"
        assert not ReviewComment.objects.filter(review=review).exists()


@pytest.mark.django_db
class TestMetricsEndpoint:
    def test_metrics_endpoint_returns_data(self, client):
        """The /metrics endpoint returns Prometheus text format."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "# HELP" in response.content.decode()
