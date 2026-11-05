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
        assert score == 40

    def test_error_severity(self):
        score = calculate_risk_score([{"severity": "error"}])
        assert score == 25

    def test_warning_severity(self):
        score = calculate_risk_score([{"severity": "warning"}])
        assert score == 10

    def test_info_severity(self):
        score = calculate_risk_score([{"severity": "info"}])
        assert score == 2

    def test_multiple_comments(self):
        comments = [
            {"severity": "critical"},
            {"severity": "error"},
            {"severity": "warning"},
        ]
        score = calculate_risk_score(comments)
        assert score == 75

    def test_caps_at_100(self):
        comments = [{"severity": "critical"}] * 10
        score = calculate_risk_score(comments)
        assert score == 100


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

    @pytest.mark.asyncio
    async def test_analyze_anchors_comments_and_reports_counts(self, caplog):
        from services.llm_client import LLMResponse

        request = ReviewRequest(
            diff="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old line\n+new line\n",
            repo_full_name="owner/repo",
            pr_number=1,
        )
        mock_response = LLMResponse(
            content=(
                '[{"file_path": "app.py", "line_number": 1, "category": "security",'
                ' "severity": "warning", "body": "On the diff", "suggested_fix": null},'
                ' {"file_path": "app.py", "line_number": 40, "category": "quality",'
                ' "severity": "info", "body": "Off the diff", "suggested_fix": null}]'
            ),
            model_used="google/gemini",
            provider="google",
            prompt_tokens=10,
            completion_tokens=5,
        )

        with patch("agents.review_agent.llm_client") as mock_llm:
            mock_llm.generate = AsyncMock(return_value=mock_response)
            with caplog.at_level("INFO", logger="services.comment_anchoring"):
                response = await analyze_review(request, secret="valid-secret")

        off = [c for c in response.comments if c.body == "Off the diff"]
        on = [c for c in response.comments if c.body == "On the diff"]
        assert off and all(c.line_number == 0 for c in off)
        assert on and all(c.line_number == 1 for c in on)
        assert response.anchored == len(on)
        assert response.unanchored == len(off)
        assert response.snapped == 0
        assert any(
            f"anchored={response.anchored}" in r.getMessage()
            and f"unanchored={response.unanchored}" in r.getMessage()
            for r in caplog.records
        )

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


class TestChunkText:
    def test_chunk_text_has_no_line_number_prefixes(self):
        from routers.review import _chunk_text
        from services.code_parser import parse_diff

        diff = (
            "--- a/app.py\n+++ b/app.py\n@@ -7,2 +7,2 @@\n keep = 1\n-x = 1\n+x = 2\n"
        )

        text = _chunk_text(parse_diff(diff)[0])

        assert "x = 2" in text
        assert "L8" not in text and "L7" not in text


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
