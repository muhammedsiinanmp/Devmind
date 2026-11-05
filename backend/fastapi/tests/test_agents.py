"""
Tests for Review Agent.
"""

import pytest
from unittest.mock import AsyncMock, patch

from agents.states import ReviewState
from agents.review_agent import (
    create_system_message,
    _parse_llm_comments,
    MAX_PARSE_RETRIES,
)


class TestReviewState:
    def test_review_state_type(self):
        state: ReviewState = {
            "diff_text": "test diff",
            "repo_full_name": "owner/repo",
            "pr_number": 1,
            "user_id": 1,
            "security_comments": [],
            "quality_comments": [],
            "test_comments": [],
            "synthesized_comments": [],
            "analyzer_runs": {},
            "model_used": "",
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
    def test_unparseable_response_retried_once(self):
        assert MAX_PARSE_RETRIES == 1


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
    async def test_synthesize_node(self):
        from agents.review_agent import synthesize

        state: ReviewState = {
            "diff_text": "test",
            "repo_full_name": "owner/repo",
            "pr_number": 1,
            "user_id": 1,
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
            "analyzer_runs": {},
            "model_used": "",
        }

        result = await synthesize(state)

        assert "synthesized_comments" in result
        comments = result["synthesized_comments"]
        assert len(comments) == 2
        assert comments[0]["severity"] == "critical"


def _llm_response(content: str, model: str = "test/model"):
    from services.llm_client import LLMResponse

    return LLMResponse(
        content=content,
        model_used=model,
        provider="test",
        prompt_tokens=11,
        completion_tokens=7,
    )


def _analyzer_of(messages: list[dict]) -> str:
    """Which analyzer sent this request (from its category system message)."""
    focus = messages[0]["content"].splitlines()[-1].lower()
    for name in ("security", "quality", "test"):
        if name in focus:
            return name
    raise AssertionError(f"unknown analyzer: {focus}")


_LARGE_DIFF = "--- a/big.py\n+++ b/big.py\n@@ -0,0 +1,200 @@\n" + "\n".join(
    f"+x_{i} = {i}" for i in range(200)
)


class TestHonestGraph:
    def test_graph_has_only_working_nodes(self):
        from agents.review_agent import build_review_graph

        nodes = set(build_review_graph().get_graph().nodes) - {
            "__start__",
            "__end__",
        }
        assert nodes == {
            "analyze_security",
            "analyze_quality",
            "analyze_tests",
            "synthesize",
        }

    @pytest.mark.asyncio
    async def test_clean_large_diff_makes_exactly_three_llm_calls(self):
        """A clean 200-line diff is reviewed once: one call per analyzer."""
        from agents.review_agent import run_review_agent

        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(return_value=_llm_response("[]"))

            result = await run_review_agent(
                diff_text=_LARGE_DIFF, repo_full_name="owner/repo"
            )

        assert mock_client.generate.await_count == 3
        assert result["synthesized_comments"] == []

    @pytest.mark.asyncio
    async def test_unparseable_response_retries_only_that_analyzer_once(self):
        from agents.review_agent import run_review_agent

        async def fake_generate(messages, user_id=None):
            if _analyzer_of(messages) == "security":
                return _llm_response("I could not produce JSON, sorry.")
            return _llm_response("[]")

        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(side_effect=fake_generate)

            result = await run_review_agent(
                diff_text=_LARGE_DIFF, repo_full_name="owner/repo"
            )

        # quality + tests once each, security twice (original + one retry)
        assert mock_client.generate.await_count == 4
        assert result["analyzer_runs"]["security"]["attempts"] == 2
        assert result["analyzer_runs"]["quality"]["attempts"] == 1
        assert result["analyzer_runs"]["tests"]["attempts"] == 1
        assert result["synthesized_comments"] == []

    @pytest.mark.asyncio
    async def test_retry_recovers_findings_after_unparseable_response(self):
        from agents.review_agent import run_review_agent

        finding = (
            '[{"file_path": "big.py", "line_number": 3, "category": "security",'
            ' "severity": "critical", "body": "eval of input",'
            ' "suggested_fix": null}]'
        )
        security_replies = iter(["not json", finding])

        async def fake_generate(messages, user_id=None):
            if _analyzer_of(messages) == "security":
                return _llm_response(next(security_replies))
            return _llm_response("[]")

        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(side_effect=fake_generate)

            result = await run_review_agent(
                diff_text=_LARGE_DIFF, repo_full_name="owner/repo"
            )

        assert [c["body"] for c in result["synthesized_comments"]] == ["eval of input"]

    @pytest.mark.asyncio
    async def test_analyzer_runs_recorded_per_analyzer(self):
        from agents.review_agent import run_review_agent

        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(
                return_value=_llm_response("[]", model="google/gemini-2.0-flash")
            )

            result = await run_review_agent(
                diff_text=_LARGE_DIFF, repo_full_name="owner/repo"
            )

        runs = result["analyzer_runs"]
        assert set(runs) == {"security", "quality", "tests"}
        for run in runs.values():
            assert run["model"] == "google/gemini-2.0-flash"
            assert run["latency_ms"] >= 0
            assert run["prompt_tokens"] == 11
            assert run["completion_tokens"] == 7
            assert run["attempts"] == 1
        assert result["model_used"] == "google/gemini-2.0-flash"

    @pytest.mark.asyncio
    async def test_model_used_does_not_depend_on_branch_order(self):
        """Each analyzer used a different model; model_used must be the
        security analyzer's, not whichever parallel branch wrote last."""
        from agents.review_agent import run_review_agent

        models = {"security": "a/one", "quality": "b/two", "test": "c/three"}

        async def fake_generate(messages, user_id=None):
            return _llm_response("[]", model=models[_analyzer_of(messages)])

        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(side_effect=fake_generate)
            result = await run_review_agent(
                diff_text=_LARGE_DIFF, repo_full_name="owner/repo"
            )

        assert result["model_used"] == "a/one"
        assert {k: v["model"] for k, v in result["analyzer_runs"].items()} == {
            "security": "a/one",
            "quality": "b/two",
            "tests": "c/three",
        }
