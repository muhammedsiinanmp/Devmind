"""
Tests for Review Agent.
"""

import pytest
from unittest.mock import AsyncMock, patch

from agents.states import ReviewState
from agents.review_agent import (
    create_system_message,
    _parse_llm_comments,
    _parse_llm_comment_list,
    MAX_PARSE_RETRIES,
)
from services.prompt_builder import REVIEW_SYSTEM_PROMPT


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

    def test_parse_empty_object_is_no_findings(self):
        """'{}' is a valid "nothing found" reply, not a parse failure."""
        assert _parse_llm_comment_list("{}", "security") == []

    def test_parse_known_key_null_is_no_findings(self):
        assert _parse_llm_comment_list('{"issues": null}', "security") == []
        assert _parse_llm_comment_list('{"findings": []}', "security") == []

    def test_parse_prose_is_unparseable(self):
        assert _parse_llm_comment_list("No issues found.", "security") is None
        assert _parse_llm_comment_list('{"verdict": "LGTM"}', "security") is None

    def test_parse_maps_high_medium_low_severities(self):
        content = (
            '[{"file_path": "a.py", "line_number": 1, "severity": "High", "body": "h"},'
            ' {"file_path": "a.py", "line_number": 2, "severity": "medium", "body": "m"},'
            ' {"file_path": "a.py", "line_number": 3, "severity": "LOW", "body": "l"}]'
        )
        comments = _parse_llm_comments(content, "security")

        assert [c["severity"] for c in comments] == ["error", "warning", "info"]


class TestPromptContract:
    def test_system_prompt_asks_for_parser_severities_not_prose(self):
        prompt = REVIEW_SYSTEM_PROMPT.lower()
        assert "critical, error, warning, info" in prompt
        assert "high/medium/low" not in prompt
        assert "review format" not in prompt

    @pytest.mark.asyncio
    async def test_analyzer_instruction_asks_for_empty_list_when_clean(self):
        from agents.review_agent import analyze_quality

        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(return_value=_llm_response("[]"))
            await analyze_quality({"diff_text": _LARGE_DIFF, "repo_full_name": "o/r"})

        messages = mock_client.generate.await_args.args[0]
        assert 'If there are no issues, reply with {"findings": []}' in (
            messages[-1]["content"]
        )


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

        async def fake_generate(messages, user_id=None, **kwargs):
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
        # A twice-failed analyzer is distinguishable from a clean one.
        assert result["analyzer_runs"]["security"]["parsed"] is False
        assert result["analyzer_runs"]["quality"]["parsed"] is True
        assert result["analyzer_runs"]["tests"]["parsed"] is True

    @pytest.mark.asyncio
    async def test_retry_recovers_findings_after_unparseable_response(self):
        from agents.review_agent import run_review_agent

        finding = (
            '[{"file_path": "big.py", "line_number": 3, "category": "security",'
            ' "severity": "critical", "body": "eval of input",'
            ' "suggested_fix": null}]'
        )
        security_replies = iter(["not json", finding])

        async def fake_generate(messages, user_id=None, **kwargs):
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

        async def fake_generate(messages, user_id=None, **kwargs):
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

    @pytest.mark.asyncio
    async def test_prose_reply_then_empty_list_is_clean_after_corrective_turn(self):
        """A model that answers "No issues found." is asked once more for
        JSON, and its [] then counts as a clean, parsed result."""
        from agents.review_agent import CORRECTIVE_PROMPT, run_review_agent

        security_replies = iter(["No issues found.", "[]"])
        security_calls: list[list[dict]] = []

        async def fake_generate(messages, user_id=None, **kwargs):
            if _analyzer_of(messages) == "security":
                security_calls.append(list(messages))
                return _llm_response(next(security_replies))
            return _llm_response("[]")

        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(side_effect=fake_generate)
            result = await run_review_agent(
                diff_text=_LARGE_DIFF, repo_full_name="owner/repo"
            )

        assert result["synthesized_comments"] == []
        run = result["analyzer_runs"]["security"]
        assert run["attempts"] == 2
        assert run["parsed"] is True
        first, second = security_calls
        assert second[: len(first)] == first
        assert second[-1] == {"role": "user", "content": CORRECTIVE_PROMPT}
        assert CORRECTIVE_PROMPT == (
            "Your previous reply was not the JSON object described in the output "
            'format. Reply with only that JSON object, or {"findings": []} if there '
            "are no issues."
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty_reply", ["", None])
    async def test_empty_first_reply_retries_without_empty_assistant_turn(
        self, empty_reply
    ):
        """Some OpenAI-compatible endpoints reject an empty assistant message,
        so after an empty reply the retry sends only the corrective turn."""
        from agents.review_agent import CORRECTIVE_PROMPT, run_review_agent

        security_replies = iter([empty_reply, "[]"])
        security_calls: list[list[dict]] = []

        async def fake_generate(messages, user_id=None, **kwargs):
            if _analyzer_of(messages) == "security":
                security_calls.append(list(messages))
                return _llm_response(next(security_replies))
            return _llm_response("[]")

        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(side_effect=fake_generate)
            result = await run_review_agent(
                diff_text=_LARGE_DIFF, repo_full_name="owner/repo"
            )

        first, second = security_calls
        assert second == first + [{"role": "user", "content": CORRECTIVE_PROMPT}]
        assert all(m["role"] != "assistant" for m in second)
        assert result["analyzer_runs"]["security"]["attempts"] == 2
        assert result["analyzer_runs"]["security"]["parsed"] is True

    @pytest.mark.asyncio
    async def test_unknown_token_counts_stay_none(self):
        from agents.review_agent import run_review_agent
        from services.llm_client import LLMResponse

        response = LLMResponse(
            content="[]",
            model_used="x/y",
            provider="test",
            prompt_tokens=None,
            completion_tokens=None,
        )
        with patch("agents.review_agent.llm_client") as mock_client:
            mock_client.generate = AsyncMock(return_value=response)
            result = await run_review_agent(
                diff_text=_LARGE_DIFF, repo_full_name="owner/repo"
            )

        for run in result["analyzer_runs"].values():
            assert run["prompt_tokens"] is None
            assert run["completion_tokens"] is None
