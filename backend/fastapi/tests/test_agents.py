"""
Tests for Review Agent.
"""

import pytest
from unittest.mock import AsyncMock, patch

from agents.states import ReviewState, ReviewComment
from agents.review_agent import (
    create_system_message,
    should_retry,
    _parse_llm_comments,
    MAX_ITERATIONS,
    CONFIDENCE_THRESHOLD,
)


class TestReviewState:
    def test_review_state_type(self):
        state: ReviewState = {
            "diff_text": "test diff",
            "repo_full_name": "owner/repo",
            "pr_number": 1,
            "user_id": 1,
            "conventions": {},
            "security_comments": [],
            "quality_comments": [],
            "test_comments": [],
            "synthesized_comments": [],
            "suggested_fixes": [],
            "model_used": "",
            "confidence": 0.0,
            "iteration": 0,
        }
        assert state["diff_text"] == "test diff"
        assert state["repo_full_name"] == "owner/repo"


class TestCreateSystemMessage:
    def test_create_security_message(self):
        msg = create_system_message("security")
        assert "security" in msg.lower()
        assert "SQL injection" in msg or "vulnerabilities" in msg.lower()

    def test_create_quality_message(self):
        msg = create_system_message("quality")
        assert "quality" in msg.lower()

    def test_create_tests_message(self):
        msg = create_system_message("tests")
        assert "test coverage" in msg.lower() or "test patterns" in msg.lower()

    def test_create_default_message(self):
        msg = create_system_message("unknown")
        assert msg is not None


class TestShouldRetry:
    def test_should_retry_below_threshold(self):
        state: ReviewState = {
            "confidence": 0.5,
            "iteration": 0,
        }
        assert should_retry(state) is True

    def test_should_retry_above_threshold(self):
        state: ReviewState = {
            "confidence": 0.8,
            "iteration": 0,
        }
        assert should_retry(state) is False

    def test_should_retry_max_iterations(self):
        state: ReviewState = {
            "confidence": 0.5,
            "iteration": MAX_ITERATIONS,
        }
        assert should_retry(state) is False

    def test_should_not_retry_first_iteration(self):
        state: ReviewState = {
            "confidence": 0.6,
            "iteration": 0,
        }
        assert should_retry(state) is True


class TestParseLLMComments:
    def test_parse_valid_json(self):
        content = '[{"file_path": "app.py", "line_number": 10, "category": "security", "severity": "critical", "body": "SQL injection", "suggested_fix": "Use parameterized query"}]'
        comments = _parse_llm_comments(content, "security")

        assert len(comments) > 0
        assert comments[0]["file_path"] == "app.py"
        assert comments[0]["severity"] == "critical"

    def test_parse_invalid_json(self):
        content = "not valid json"
        comments = _parse_llm_comments(content, "security")

        assert comments == []

    def test_parse_empty(self):
        comments = _parse_llm_comments("", "security")

        assert comments == []


class TestConstants:
    def test_confidence_threshold(self):
        assert CONFIDENCE_THRESHOLD == 0.7

    def test_max_iterations(self):
        assert MAX_ITERATIONS == 3


class TestReviewGraph:
    @pytest.mark.asyncio
    async def test_build_review_graph(self):
        from agents.review_agent import build_review_graph

        graph = build_review_graph()
        assert graph is not None

    @pytest.mark.asyncio
    async def test_run_review_agent_with_mock(self):
        from agents.review_agent import run_review_agent
        from services.llm_client import LLMResponse

        mock_response = LLMResponse(
            content="[{'file_path': 'test.py', 'line_number': 1, 'category': 'security', 'severity': 'warning', 'body': 'Test', 'suggested_fix': None}]",
            model_used="test/model",
            provider="test",
            prompt_tokens=10,
            completion_tokens=5,
        )

        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(return_value=mock_response)

            result = await run_review_agent(
                diff_text="--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n+new line",
                repo_full_name="owner/repo",
            )

            assert "synthesized_comments" in result or "security_comments" in result


class TestNodes:
    @pytest.mark.asyncio
    async def test_fetch_conventions_node(self):
        from agents.review_agent import fetch_conventions

        state: ReviewState = {
            "diff_text": "test",
            "repo_full_name": "owner/repo",
            "pr_number": 1,
            "user_id": 1,
            "conventions": {},
            "security_comments": [],
            "quality_comments": [],
            "test_comments": [],
            "synthesized_comments": [],
            "suggested_fixes": [],
            "model_used": "",
            "confidence": 0.0,
            "iteration": 0,
        }

        result = await fetch_conventions(state)
        assert "conventions" in result

    @pytest.mark.asyncio
    async def test_synthesize_node(self):
        from agents.review_agent import synthesize

        state: ReviewState = {
            "diff_text": "test",
            "repo_full_name": "owner/repo",
            "pr_number": 1,
            "user_id": 1,
            "conventions": {},
            "security_comments": [
                {
                    "file_path": "a.py",
                    "line_number": 10,
                    "category": "security",
                    "severity": "warning",
                    "body": "Issue 1",
                    "suggested_fix": None,
                },
                {
                    "file_path": "b.py",
                    "line_number": 20,
                    "category": "security",
                    "severity": "critical",
                    "body": "Issue 2",
                    "suggested_fix": "Fix it",
                },
            ],
            "quality_comments": [],
            "test_comments": [],
            "synthesized_comments": [],
            "suggested_fixes": [],
            "model_used": "",
            "confidence": 0.0,
            "iteration": 0,
        }

        result = await synthesize(state)

        assert "synthesized_comments" in result
        comments = result["synthesized_comments"]
        assert len(comments) == 2
        assert comments[0]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_format_output_node(self):
        from agents.review_agent import format_output

        state: ReviewState = {
            "diff_text": "test",
            "repo_full_name": "owner/repo",
            "pr_number": 1,
            "user_id": 1,
            "conventions": {},
            "security_comments": [],
            "quality_comments": [],
            "test_comments": [],
            "synthesized_comments": [
                {
                    "file_path": "a.py",
                    "line_number": 10,
                    "category": "security",
                    "severity": "warning",
                    "body": "Good comment",
                    "suggested_fix": None,
                },
            ],
            "suggested_fixes": [],
            "model_used": "",
            "confidence": 0.0,
            "iteration": 0,
        }

        result = await format_output(state)

        assert "confidence" in result
        assert result["confidence"] == 1.0
