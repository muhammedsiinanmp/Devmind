"""
Tests for review router endpoint.
"""

import pytest
from unittest.mock import AsyncMock, patch

from routers.review import analyze_review, calculate_risk_score
from models.review import ReviewRequest, ReviewComment


class TestCalculateRiskScore:
    def test_empty_comments(self):
        score = calculate_risk_score([])
        assert score == 0

    def test_critical_severity(self):
        score = calculate_risk_score([{"severity": "critical"}])
        assert score == 70

    def test_error_severity(self):
        score = calculate_risk_score([{"severity": "error"}])
        assert score == 45

    def test_warning_severity(self):
        score = calculate_risk_score([{"severity": "warning"}])
        assert score == 20

    def test_info_severity(self):
        score = calculate_risk_score([{"severity": "info"}])
        assert score == 5

    def test_multiple_comments(self):
        """Highest severity base (critical 70) + 3 per other finding above info."""
        comments = [
            {"severity": "warning"},
            {"severity": "critical"},
            {"severity": "error"},
            {"severity": "info"},
        ]
        score = calculate_risk_score(comments)
        assert score == 76

    def test_extra_findings_add_at_most_15(self):
        comments = [{"severity": "critical"}] * 10
        score = calculate_risk_score(comments)
        assert score == 85

    def test_unknown_severity_counts_as_info(self):
        assert calculate_risk_score([{"severity": "blocker"}, {}]) == 5

    def test_ten_info_notes_score_below_one_critical(self):
        ten_info = calculate_risk_score([{"severity": "info"}] * 10)
        one_critical = calculate_risk_score([{"severity": "critical"}])
        assert ten_info < one_critical

    def test_nitpicks_never_outscore_one_critical(self):
        one_critical = calculate_risk_score([{"severity": "critical"}])
        assert calculate_risk_score([{"severity": "info"}] * 50) < one_critical
        assert calculate_risk_score([{"severity": "warning"}] * 50) < one_critical


class TestReviewModels:
    def test_review_comment(self):
        comment = ReviewComment(
            file_path="app.py",
            line_number=10,
            category="security",
            severity="critical",
            body="SQL injection vulnerability",
            suggested_fix="Use parameterized queries",
        )
        assert comment.file_path == "app.py"
        assert comment.severity == "critical"

    def test_review_request(self):
        request = ReviewRequest(
            diff="--- a/app.py\n+++ b/app.py",
            repo_full_name="owner/repo",
            pr_number=123,
        )
        assert request.repo_full_name == "owner/repo"
        assert request.pr_number == 123


class TestAnalyzeEndpoint:
    @pytest.mark.asyncio
    async def test_analyze_with_secret(self):
        from services.llm_client import LLMResponse

        request = ReviewRequest(
            diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n+new line",
            repo_full_name="owner/repo",
            pr_number=1,
        )

        mock_response = LLMResponse(
            content='[{"file_path": "app.py", "line_number": 1, "category": "security", "severity": "warning", "body": "Good", "suggested_fix": null}]',
            model_used="google/gemini",
            provider="google",
            prompt_tokens=10,
            completion_tokens=5,
        )

        with patch("agents.review_agent.llm_client") as mock_llm:
            mock_llm.generate = AsyncMock(return_value=mock_response)

            response = await analyze_review(request, secret="valid-secret")

            assert response.repo_full_name == "owner/repo"
            assert response.pr_number == 1
            assert response.risk_score >= 0
            assert response.risk_score <= 100
            assert set(response.analyzer_runs) == {"security", "quality", "tests"}
            assert response.analyzer_runs["security"].model == "google/gemini"
            assert response.analyzer_runs["security"].prompt_tokens == 10
            assert response.analyzer_runs["security"].parsed is True

    @pytest.mark.asyncio
    async def test_analyze_reports_unparsed_analyzer(self):
        """An analyzer whose replies never parse is reported as parsed=False
        in the response, distinct from a clean analyzer."""
        from services.llm_client import LLMResponse

        request = ReviewRequest(
            diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n+new line",
            repo_full_name="owner/repo",
            pr_number=1,
        )

        async def fake_generate(messages, user_id=None):
            focus = messages[0]["content"].splitlines()[-1].lower()
            content = "Looks fine to me." if "security" in focus else "[]"
            return LLMResponse(
                content=content,
                model_used="google/gemini",
                provider="google",
                prompt_tokens=10,
                completion_tokens=5,
            )

        with patch("agents.review_agent.llm_client") as mock_llm:
            mock_llm.generate = AsyncMock(side_effect=fake_generate)

            response = await analyze_review(request, secret="valid-secret")

        runs = response.analyzer_runs
        assert runs["security"].parsed is False
        assert runs["security"].attempts == 2
        assert runs["quality"].parsed is True
        assert runs["tests"].parsed is True
        assert response.comments == []

    def test_analyzer_run_requires_parsed(self):
        from pydantic import ValidationError

        from models.review import AnalyzerRun

        with pytest.raises(ValidationError):
            AnalyzerRun(model="m", latency_ms=1)

    @pytest.mark.asyncio
    async def test_analyze_handles_error(self):
        request = ReviewRequest(
            diff="test diff",
            repo_full_name="owner/repo",
            pr_number=1,
        )

        with patch("agents.review_agent.llm_client") as mock_llm:
            mock_llm.generate.side_effect = Exception("Test error")

            with pytest.raises(Exception):
                await analyze_review(request, secret="valid-secret")


class TestReviewRouter:
    def test_router_exists(self):
        from routers.review import router

        assert router is not None

    def test_router_prefix(self):
        from routers.review import router

        assert router.prefix == "/review"

    def test_router_tags(self):
        from routers.review import router

        assert "review" in router.tags
