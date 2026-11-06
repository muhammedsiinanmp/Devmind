"""
Tests for reviewing large diffs file by file (A5).

The LLM is a fake that answers from the prompt it is sent, so these check
what each batch's prompt contains and what the merged review reports.
"""

import asyncio
import json
import re
from unittest.mock import AsyncMock, patch

import pytest

from core.config import DEFAULT_SKIP_PATTERNS, get_settings
from models.review import ReviewRequest
from services.code_parser import parse_diff
from services.diff_batching import is_skipped_path, plan_batches
from services.llm_client import AllProvidersDownError, LLMResponse
from services.prompt_builder import (
    PromptContext,
    build_review_prompt,
    diff_token_budget,
)

MARKER = "LAST_FILE_MARKER = os.environ['TOKEN']"


def _new_file(path: str, lines: int, marker_at: int | None = None) -> str:
    """Diff adding a file of ``lines`` long-ish lines, MARKER at ``marker_at``."""
    body = []
    for i in range(1, lines + 1):
        if i == marker_at:
            body.append(f"+{MARKER}")
        else:
            body.append(
                f"+value_{i} = compute_total(argument_{i}, weight_{i}, "
                f"offset={i}, label='row {i} of {path}')"
            )
    return (
        f"diff --git a/{path} b/{path}\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{lines} @@\n" + "\n".join(body) + "\n"
    )


SMALL_FILE = (
    "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
    "@@ -1,1 +1,2 @@\n import os\n+os.system(user_input)\n"
)
UV_LOCK = (
    "diff --git a/uv.lock b/uv.lock\n--- a/uv.lock\n+++ b/uv.lock\n"
    '@@ -1,1 +1,2 @@\n version = 1\n+name = "requests"\n'
)

# Three files whose rendering together is far over one prompt's budget. The
# marker is the 100th line of the last file: within the 120 lines a hunk may
# show, but beyond the file's share when all three files share one prompt.
OVER_BUDGET_DIFF = (
    _new_file("pkg/first.py", 220)
    + _new_file("pkg/second.py", 220)
    + _new_file("pkg/third.py", 220, marker_at=100)
)


def _files_in(prompt: str) -> list[str]:
    return re.findall(r"^File: (.+)$", prompt, re.M)


class FakeLLM:
    """Reports a finding wherever MARKER is shown, with its line number."""

    def __init__(self, delay: float = 0.0, fail_on: str | None = None):
        self.prompts: list[str] = []
        self.delay = delay
        self.fail_on = fail_on
        self.in_flight: list[str] = []
        self.max_calls_in_flight = 0
        self.max_batches_in_flight = 0

    async def __call__(self, messages, **kwargs):
        prompt = messages[1]["content"]
        batch = ",".join(_files_in(prompt))
        self.prompts.append(prompt)
        self.in_flight.append(batch)
        self.max_calls_in_flight = max(self.max_calls_in_flight, len(self.in_flight))
        self.max_batches_in_flight = max(
            self.max_batches_in_flight, len(set(self.in_flight))
        )
        try:
            await asyncio.sleep(self.delay)
            if self.fail_on and self.fail_on in batch:
                raise AllProvidersDownError("all providers rate limited")
            findings = []
            match = re.search(rf"^L(\d+) +\+ {re.escape(MARKER)}$", prompt, re.M)
            if match:
                findings.append(
                    {
                        "file_path": "pkg/third.py",
                        "line_number": int(match.group(1)),
                        "category": "security",
                        "severity": "error",
                        "body": "Token read from the environment and kept in a global",
                        "suggested_fix": None,
                    }
                )
            return LLMResponse(
                content=json.dumps({"findings": findings}),
                model_used="test/model",
                provider="test",
                prompt_tokens=10,
                completion_tokens=2,
            )
        finally:
            self.in_flight.remove(batch)


async def _run(diff: str, fake: FakeLLM, **kwargs) -> dict:
    from agents.review_agent import run_review_agent

    with patch("agents.review_agent.llm_client") as client:
        client.generate = fake
        return await run_review_agent(diff_text=diff, repo_full_name="o/r", **kwargs)


@pytest.fixture
def settings(monkeypatch):
    """The cached settings object, with changes undone after the test."""
    s = get_settings()
    for name in (
        "review_max_batches",
        "review_max_concurrent_batches",
        "review_skip_patterns",
    ):
        monkeypatch.setattr(s, name, getattr(s, name))
    return s


class TestOverBudgetDiff:
    def test_one_prompt_would_hide_the_marker(self):
        # Without batching the last file's marker line is cut from the prompt.
        prompt = build_review_prompt(
            PromptContext(diff_chunks=parse_diff(OVER_BUDGET_DIFF))
        )
        assert MARKER not in prompt
        assert "lines omitted" in prompt

    @pytest.mark.asyncio
    async def test_three_file_diff_over_budget_gets_findings_from_the_last_file(
        self, settings
    ):
        fake = FakeLLM()
        result = await _run(OVER_BUDGET_DIFF, fake)

        findings = [
            (c["file_path"], c["line_number"]) for c in result["synthesized_comments"]
        ]
        assert findings == [("pkg/third.py", 100)]
        assert result["files_reviewed"] == [
            "pkg/first.py",
            "pkg/second.py",
            "pkg/third.py",
        ]
        assert result["files_skipped"] == []
        # Every batch fits: no prompt is over budget or loses lines to it.
        batches = {tuple(_files_in(p)) for p in fake.prompts}
        assert len(batches) > 1
        assert sorted(f for b in batches for f in b) == result["files_reviewed"]
        for prompt in fake.prompts:
            assert "omitted to fit the prompt" not in prompt

    @pytest.mark.asyncio
    async def test_analyzer_runs_are_summed_over_batches(self, settings):
        fake = FakeLLM()
        result = await _run(OVER_BUDGET_DIFF, fake)

        batches = len({tuple(_files_in(p)) for p in fake.prompts})
        assert len(fake.prompts) == 3 * batches
        for run in result["analyzer_runs"].values():
            assert run["attempts"] == batches
            assert run["prompt_tokens"] == 10 * batches
            assert run["parsed"] is True
        assert result["model_used"] == "test/model"


class TestSkippedFiles:
    @pytest.mark.asyncio
    async def test_uv_lock_is_skipped_and_reported(self, settings):
        fake = FakeLLM()
        result = await _run(SMALL_FILE + UV_LOCK, fake)

        assert result["files_reviewed"] == ["app.py"]
        assert result["files_skipped"] == [
            {"file_path": "uv.lock", "reason": "generated"}
        ]
        assert len(fake.prompts) == 3
        assert not any("uv.lock" in p or "requests" in p for p in fake.prompts)

    @pytest.mark.asyncio
    async def test_diff_of_only_generated_files_makes_no_llm_call(self, settings):
        fake = FakeLLM()
        result = await _run(UV_LOCK, fake)

        assert fake.prompts == []
        assert result["synthesized_comments"] == []
        assert result["files_skipped"] == [
            {"file_path": "uv.lock", "reason": "generated"}
        ]

    @pytest.mark.parametrize(
        "path",
        [
            "uv.lock",
            "backend/fastapi/uv.lock",
            "frontend/pnpm-lock.yaml",
            "static/js/app.min.js",
            "web/__snapshots__/Button.test.tsx.snap",
            "drizzle/meta/0001_snapshot.json",
            "vendor/github.com/x/y.go",
            "api/v1/user_pb2.py",
        ],
    )
    def test_default_patterns_skip_generated_files(self, path):
        assert is_skipped_path(path, DEFAULT_SKIP_PATTERNS)

    @pytest.mark.parametrize(
        "path",
        [
            "app.py",
            "apps/reviews/migrations/0003_add_field.py",
            "src/lock.py",
            "docs/vendor-notes.md",
        ],
    )
    def test_default_patterns_keep_source_files(self, path):
        assert not is_skipped_path(path, DEFAULT_SKIP_PATTERNS)

    @pytest.mark.asyncio
    async def test_skip_patterns_are_configurable(self, settings):
        settings.review_skip_patterns = ["app.py"]
        fake = FakeLLM()
        result = await _run(SMALL_FILE + UV_LOCK, fake)

        assert result["files_reviewed"] == ["uv.lock"]
        assert result["files_skipped"] == [
            {"file_path": "app.py", "reason": "generated"}
        ]


class TestBatchLimits:
    @pytest.mark.asyncio
    async def test_files_beyond_the_batch_cap_are_skipped(self, settings):
        settings.review_max_batches = 1
        fake = FakeLLM()
        result = await _run(OVER_BUDGET_DIFF, fake)

        assert len(fake.prompts) == 3
        reviewed = result["files_reviewed"]
        skipped = result["files_skipped"]
        assert reviewed and skipped
        assert reviewed + [s["file_path"] for s in skipped] == [
            "pkg/first.py",
            "pkg/second.py",
            "pkg/third.py",
        ]
        assert {s["reason"] for s in skipped} == {"batch_limit"}
        assert not any(f in p for p in fake.prompts for f in _skipped(skipped))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [1, 2])
    async def test_concurrent_batches_are_bounded(self, settings, limit):
        settings.review_max_concurrent_batches = limit
        diff = "".join(_new_file(f"pkg/mod{i}.py", 220) for i in range(5))
        fake = FakeLLM(delay=0.02)
        result = await _run(diff, fake)

        assert len(result["files_reviewed"]) == 5
        assert len({tuple(_files_in(p)) for p in fake.prompts}) == 3
        assert fake.max_batches_in_flight == limit
        assert fake.max_calls_in_flight == 3 * limit

    @pytest.mark.asyncio
    async def test_a_failing_batch_raises_its_own_error(self, settings):
        fake = FakeLLM(fail_on="pkg/second.py")
        with pytest.raises(AllProvidersDownError):
            await _run(OVER_BUDGET_DIFF, fake)


def _skipped(skipped: list[dict]) -> list[str]:
    return [f"File: {s['file_path']}" for s in skipped]


class TestPlan:
    def test_diff_that_fits_is_one_batch_of_every_chunk(self):
        chunks = parse_diff(SMALL_FILE + _new_file("pkg/a.py", 40))
        plan = plan_batches(chunks, diff_token_budget(PromptContext()), [], 6)

        assert plan.batches == [chunks]
        assert plan.files_reviewed == ["app.py", "pkg/a.py"]

    def test_every_batch_fits_the_budget(self):
        # Two of these files fit in one prompt, so four make two batches.
        chunks = parse_diff("".join(_new_file(f"m{i}.py", 220) for i in range(4)))
        plan = plan_batches(chunks, diff_token_budget(PromptContext()), [], 6)

        assert [[c.file_path for c in b] for b in plan.batches] == [
            ["m0.py", "m1.py"],
            ["m2.py", "m3.py"],
        ]
        for batch in plan.batches:
            prompt = build_review_prompt(PromptContext(diff_chunks=batch))
            # Each file shows all 120 lines its hunk may show on its own.
            assert len(re.findall(r"^L\d+ +\+ ", prompt, re.M)) == 120 * len(batch)
            assert "omitted to fit the prompt" not in prompt


class TestRouterReportsCoverage:
    @pytest.mark.asyncio
    async def test_response_lists_reviewed_and_skipped_files(self, settings):
        from routers.review import analyze_review

        fake = FakeLLM()
        with (
            patch("agents.review_agent.llm_client") as client,
            patch(
                "services.vector_store.vector_store.generate_embeddings",
                AsyncMock(side_effect=RuntimeError("no embeddings in tests")),
            ),
            patch("routers.review.store_review_async", AsyncMock()),
        ):
            client.generate = fake
            response = await analyze_review(
                ReviewRequest(diff=SMALL_FILE + UV_LOCK, repo_full_name="o/r"),
                secret="unused",
            )

        body = response.model_dump()
        assert body["files_reviewed"] == ["app.py"]
        assert body["files_skipped"] == [
            {"file_path": "uv.lock", "reason": "generated"}
        ]
