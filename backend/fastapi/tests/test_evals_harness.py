"""
End-to-end tests for the eval harness in replay mode, using hand-written
fixture responses (tests/fixtures/evals/responses.yaml), never a real model.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from evals import run as eval_run
from evals.cases import CASES_DIR, load_cases
from evals.cassette import (
    CALL_KEYS,
    CASSETTE_KEYS,
    Recorder,
    SecretInResponse,
    load_cassette,
)
from services.llm_client import LLMProvider, LLMResponse, llm_client

FIXTURE = yaml.safe_load(
    (Path(__file__).parent / "fixtures" / "evals" / "responses.yaml").read_text()
)
FIXTURE_IDS = set(FIXTURE["responses"])


def _fake_generate(case_id: str, model: str = FIXTURE["model_used"]):
    async def generate(messages, *, user_id=None, **kwargs):
        return LLMResponse(
            content=FIXTURE["responses"][case_id],
            model_used=model,
            provider=LLMProvider.CUSTOM,
            prompt_tokens=100,
            completion_tokens=20,
        )

    return generate


async def _record(cassettes: Path, cases):
    """Record fixture responses through the live code path into cassettes."""
    for case in cases:
        with patch.object(llm_client, "generate", _fake_generate(case.id)):
            outcome = await eval_run.live_case(case, cassettes)
        assert outcome.error is None, outcome.error


@pytest.fixture
def fixture_cases():
    return load_cases(CASES_DIR, FIXTURE_IDS)


@pytest.fixture
async def cassettes(tmp_path, fixture_cases):
    await _record(tmp_path, fixture_cases)
    return tmp_path


async def _replay_report(cases, cassettes_dir):
    outcomes = await eval_run.run("replay", cases, cassettes_dir)
    return eval_run.build_report(outcomes, "replay", "abc123", False, None)


class TestReplayScoring:
    async def test_scores_fixture_responses(self, fixture_cases, cassettes):
        report = await _replay_report(fixture_cases, cassettes)
        m = report["metrics"]
        assert report["errors"] == {}
        assert report["case_count"] == 3
        assert report["models_used"] == ["fixture/hand-written"]
        assert (m["matched"], m["partial"], m["missed"], m["extra"]) == (1, 1, 0, 1)
        assert m["precision"] == pytest.approx(1 / 3)
        assert m["recall"] == pytest.approx(1 / 2)
        assert m["clean_false_positive_rate"] == 0.0
        # line 40 is outside the sql diff; lines 22 and 7 are inside
        assert m["valid_line_rate"] == pytest.approx(2 / 3)
        assert report["cost_usd"] is None  # no prices configured

    async def test_replay_is_deterministic(self, fixture_cases, cassettes):
        first = await _replay_report(fixture_cases, cassettes)
        second = await _replay_report(fixture_cases, cassettes)
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    async def test_changed_prompt_is_reported_as_stale(self, fixture_cases, cassettes):
        # Simulate the agent's prompts changing after recording: no recorded
        # hash matches the prompts the agent now sends.
        for path in cassettes.glob("*.json"):
            data = json.loads(path.read_text())
            for call in data["calls"]:
                call["prompt_sha256"] = "f" * 64
            path.write_text(json.dumps(data))
        report = await _replay_report(fixture_cases, cassettes)
        assert set(report["errors"]) == FIXTURE_IDS
        assert all("CassetteMiss" in e for e in report["errors"].values())
        assert report["cases_scored"] == 0

    async def test_changed_case_diff_is_reported_as_stale(
        self, fixture_cases, cassettes
    ):
        case = fixture_cases[0]
        path = cassettes / f"{case.id}.json"
        data = json.loads(path.read_text())
        data["case_sha256"] = "0" * 64
        path.write_text(json.dumps(data))
        report = await _replay_report(fixture_cases, cassettes)
        assert "changed since it was recorded" in report["errors"][case.id]


class TestCassetteContents:
    async def test_cassettes_hold_only_hashes_and_responses(
        self, fixture_cases, cassettes
    ):
        for case in fixture_cases:
            path = cassettes / f"{case.id}.json"
            data = json.loads(path.read_text())
            assert set(data) == CASSETTE_KEYS
            assert data["calls"], case.id
            for call in data["calls"]:
                assert set(call) == CALL_KEYS
            text = path.read_text()
            # The prompt (which embeds the diff) is not stored, only its hash.
            assert case.diff.splitlines()[-1] not in text
            # conftest.py sets these fake provider keys; none may leak.
            for key in ("test-google-key", "test-groq-key", "test-github-token"):
                assert key not in text
            load_cassette(path, case.id, case.digest)  # round-trips

    async def test_recorder_refuses_response_containing_a_secret(self):
        async def leaky(messages, *, user_id=None, **kwargs):
            return LLMResponse("key is test-groq-key", "x/y", LLMProvider.CUSTOM, 1, 1)

        recorder = Recorder(leaky, secrets=["test-groq-key"])
        with pytest.raises(SecretInResponse):
            await recorder([{"role": "user", "content": "hi"}])
        assert recorder.calls == []


class TestCli:
    def test_replay_without_cassettes_exits_2(self, tmp_path, capsys):
        code = eval_run.main(["--replay", "--cassettes-dir", str(tmp_path)])
        assert code == 2
        assert "has not been recorded yet" in capsys.readouterr().err

    def test_record_requires_live(self):
        with pytest.raises(SystemExit):
            eval_run.main(["--replay", "--record"])

    async def test_replay_writes_results(self, cassettes, tmp_path, capsys):
        results = tmp_path / "results"
        # main() calls asyncio.run, so run it outside this test's event loop.
        import asyncio

        code = await asyncio.to_thread(
            eval_run.main,
            [
                "--replay",
                "--cassettes-dir",
                str(cassettes),
                "--only",
                ",".join(sorted(FIXTURE_IDS)),
                "--results-dir",
                str(results),
            ],
        )
        assert code == 0
        json_files = list(results.glob("*.json"))
        md_files = list(results.glob("*.md"))
        assert len(json_files) == 1 and len(md_files) == 1
        report = json.loads(json_files[0].read_text())
        assert report["mode"] == "replay"
        assert report["case_count"] == 3
        md = md_files[0].read_text()
        assert report["commit"] in md
        assert "fixture/hand-written" in md
        assert "Precision | 0.333" in md
