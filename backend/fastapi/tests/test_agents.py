"""
Tests for Review Agent.
"""

import pytest
from unittest.mock import AsyncMock, patch

from agents.states import ReviewState
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

    def test_parse_markdown_fenced_json(self):
        """Gemini frequently wraps output in ```json fences."""
        content = '```json\n[{"file_path": "app.py", "line_number": 5, "category": "security", "severity": "critical", "body": "Hardcoded secret", "suggested_fix": null}]\n```'
        comments = _parse_llm_comments(content, "security")

        assert len(comments) == 1
        assert comments[0]["file_path"] == "app.py"
        assert comments[0]["severity"] == "critical"

    def test_parse_plain_code_fence(self):
        """Handle ``` without json label."""
        content = '```\n[{"file_path": "main.py", "line_number": 1, "category": "quality", "severity": "warning", "body": "Missing docstring", "suggested_fix": null}]\n```'
        comments = _parse_llm_comments(content, "quality")

        assert len(comments) == 1
        assert comments[0]["body"] == "Missing docstring"

    def test_parse_prefix_text_before_array(self):
        """LLM adds prose before the JSON array."""
        content = 'Here are the security issues I found:\n[{"file_path": "views.py", "line_number": 42, "category": "security", "severity": "error", "body": "XSS risk", "suggested_fix": "Escape output"}]'
        comments = _parse_llm_comments(content, "security")

        assert len(comments) == 1
        assert comments[0]["body"] == "XSS risk"

    def test_parse_dict_wrapped_array(self):
        """LLM returns {"issues": [...]} instead of a bare array."""
        content = '{"issues": [{"file_path": "db.py", "line_number": 10, "category": "security", "severity": "critical", "body": "SQL injection", "suggested_fix": "Use ORM"}]}'
        comments = _parse_llm_comments(content, "security")

        assert len(comments) == 1
        assert comments[0]["severity"] == "critical"

    def test_parse_dict_wrapped_findings_key(self):
        """Handle 'findings' key in dict-wrapped response."""
        content = '{"findings": [{"file_path": "api.py", "line_number": 7, "category": "quality", "severity": "warning", "body": "No error handling", "suggested_fix": null}]}'
        comments = _parse_llm_comments(content, "quality")

        assert len(comments) == 1

    def test_parse_invalid_severity_normalised(self):
        """Unknown severity values are normalised to 'warning'."""
        content = '[{"file_path": "a.py", "line_number": 1, "category": "security", "severity": "BLOCKER", "body": "Issue", "suggested_fix": null}]'
        comments = _parse_llm_comments(content, "security")

        assert len(comments) == 1
        assert comments[0]["severity"] == "warning"

    def test_parse_default_category_applied(self):
        """Items missing category fall back to default_category."""
        content = '[{"file_path": "a.py", "line_number": 1, "severity": "warning", "body": "Issue", "suggested_fix": null}]'
        comments = _parse_llm_comments(content, "tests")

        assert len(comments) == 1
        assert comments[0]["category"] == "tests"

    def test_parse_skips_non_dict_items(self):
        """Non-dict items in the array are silently skipped."""
        content = '[{"file_path": "a.py", "line_number": 1, "category": "security", "severity": "warning", "body": "Issue", "suggested_fix": null}, "stray string", 42]'
        comments = _parse_llm_comments(content, "security")

        assert len(comments) == 1


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

    @pytest.mark.asyncio
    async def test_format_output_zero_comments_large_diff(self):
        """0 comments on a 200-line diff must produce confidence < 0.7."""
        from agents.review_agent import format_output

        large_diff = "\n".join(f"+line {i}" for i in range(200))
        state: ReviewState = {
            "diff_text": large_diff,
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

        result = await format_output(state)

        assert result["confidence"] == 0.0
        assert result["confidence"] < 0.7

    @pytest.mark.asyncio
    async def test_format_output_small_diff_no_comments(self):
        """Small diff (≤10 lines) with 0 comments is acceptable — confidence stays 1.0."""
        from agents.review_agent import format_output

        state: ReviewState = {
            "diff_text": "+one line change",
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

        result = await format_output(state)

        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_format_output_enough_comments_large_diff(self):
        """Enough comments on a large diff must reach confidence >= 0.7."""
        from agents.review_agent import format_output

        large_diff = "\n".join(f"+line {i}" for i in range(200))
        # 200 lines → expected_min = 4; 4 comments → confidence = 1.0
        comments = [
            {
                "file_path": f"f{i}.py",
                "line_number": i,
                "category": "security",
                "severity": "warning",
                "body": f"Issue {i}",
                "suggested_fix": None,
            }
            for i in range(4)
        ]
        state: ReviewState = {
            "diff_text": large_diff,
            "repo_full_name": "owner/repo",
            "pr_number": 1,
            "user_id": 1,
            "conventions": {},
            "security_comments": [],
            "quality_comments": [],
            "test_comments": [],
            "synthesized_comments": comments,
            "suggested_fixes": [],
            "model_used": "",
            "confidence": 0.0,
            "iteration": 0,
        }

        result = await format_output(state)

        assert result["confidence"] >= 0.7

    def test_should_retry_fires_when_confidence_zero(self):
        """Retry must fire when confidence is 0.0 (0 comments on large diff)."""
        state: ReviewState = {
            "confidence": 0.0,
            "iteration": 0,
        }
        assert should_retry(state) is True

    def test_should_retry_stops_at_max_iterations(self):
        """Retry must not fire past MAX_ITERATIONS even if confidence is low."""
        state: ReviewState = {
            "confidence": 0.0,
            "iteration": MAX_ITERATIONS,
        }
        assert should_retry(state) is False
