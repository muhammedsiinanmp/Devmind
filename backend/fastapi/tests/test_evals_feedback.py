"""
Eval harness feedback injection (issue #74): case files give feedback
examples straight to the agent (no database), --no-feedback runs them
without, under their own cassettes, and the case-set hash covers them.
"""

from unittest.mock import patch

import pytest

from evals import run as eval_run
from evals.cases import CASES_DIR, load_cases
from services.llm_client import LLMProvider, LLMResponse, llm_client

FEEDBACK_IDS = {
    "feedback-md5-cache-key",
    "feedback-random-jitter",
    "feedback-control-md5-password",
}


class _Capture:
    def __init__(self):
        self.prompts: list[str] = []

    async def __call__(self, messages, *, user_id=None, **kwargs):
        self.prompts.append(messages[1]["content"])
        return LLMResponse(
            content='{"findings": []}',
            model_used="test/model",
            provider=LLMProvider.CUSTOM,
            prompt_tokens=1,
            completion_tokens=1,
        )


@pytest.fixture
def case():
    [case] = load_cases(CASES_DIR, {"feedback-md5-cache-key"})
    return case


async def _prompts(case) -> list[str]:
    capture = _Capture()
    with patch.object(llm_client, "generate", capture):
        await eval_run._run_agent(case, capture)
    return capture.prompts


class TestFeedbackInjection:
    @pytest.mark.asyncio
    async def test_examples_reach_every_analyzer_prompt(self, case):
        prompts = await _prompts(case)
        assert len(prompts) == 3
        for prompt in prompts:
            assert "=== PREVIOUSLY REJECTED FINDINGS ===" in prompt
            assert "MD5 is a broken hash function" in prompt

    @pytest.mark.asyncio
    async def test_without_feedback_the_prompt_has_no_examples(self, case):
        prompts = await _prompts(case.without_feedback())
        assert not any("PREVIOUSLY REJECTED" in p for p in prompts)

    def test_no_feedback_variant_has_its_own_cassette(self, case):
        assert case.cassette_stem == "feedback-md5-cache-key"
        assert case.without_feedback().cassette_stem == (
            "feedback-md5-cache-key.no-feedback"
        )

    def test_cases_without_examples_keep_their_cassettes(self):
        [plain] = load_cases(CASES_DIR, {"weak-password-hash"})
        assert plain.without_feedback() is plain
        assert plain.cassette_stem == "weak-password-hash"
        assert plain.feedback_context() is None

    @pytest.mark.asyncio
    async def test_live_record_and_replay_use_the_variant_cassette(
        self, case, tmp_path
    ):
        stripped = case.without_feedback()
        with patch.object(llm_client, "generate", _Capture()):
            recorded = await eval_run.live_case(stripped, tmp_path)
        assert recorded.error is None
        assert [p.name for p in tmp_path.iterdir()] == [
            "feedback-md5-cache-key.no-feedback.json"
        ]

        replayed = await eval_run.replay_case(stripped, tmp_path)
        assert replayed.error is None
        # The with-feedback prompts differ, so its own cassette is needed.
        missing = await eval_run.replay_case(case, tmp_path)
        assert missing.error is not None


class TestCaseSetHash:
    def test_hash_covers_feedback(self, case):
        assert eval_run.case_set_sha256([case]) != eval_run.case_set_sha256(
            [case.without_feedback()]
        )

    def test_hash_of_cases_without_feedback_is_unchanged(self):
        import hashlib
        import json
        from dataclasses import asdict

        cases = load_cases(CASES_DIR, {"weak-password-hash", "clean-docstring"})
        before = hashlib.sha256(
            json.dumps(
                [
                    {
                        "id": c.id,
                        "diff": c.digest,
                        "expected": [asdict(e) for e in c.expected],
                    }
                    for c in cases
                ],
                sort_keys=True,
                default=list,
            ).encode()
        ).hexdigest()
        assert eval_run.case_set_sha256(cases) == before


def test_no_feedback_flag_is_recorded_in_run_flags(tmp_path, monkeypatch, capsys):
    captured = {}

    async def fake_run(mode, cases, cassettes_dir, record=False, **kwargs):
        captured["cases"] = cases
        return []

    monkeypatch.setattr(eval_run, "run", fake_run)
    (tmp_path / "x.json").write_text("{}")
    eval_run.main(
        [
            "--replay",
            "--no-feedback",
            "--cassettes-dir",
            str(tmp_path),
            "--only",
            ",".join(sorted(FEEDBACK_IDS)),
        ]
    )
    assert {c.cassette_stem for c in captured["cases"]} == {
        f"{case_id}.no-feedback" for case_id in FEEDBACK_IDS
    }
    assert '"feedback": false' in capsys.readouterr().out
