"""
End-to-end tests for the eval harness in replay mode, using hand-written
fixture responses (tests/fixtures/evals/responses.yaml), never a real model.
"""

import asyncio
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from evals import run as eval_run
from evals.cases import CASES_DIR, load_cases
from evals.cassette import (
    CALL_KEYS,
    CASSETTE_KEYS,
    OPTIONAL_CALL_KEYS,
    OPTIONAL_CASSETTE_KEYS,
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
            assert set(data) == CASSETTE_KEYS | OPTIONAL_CASSETTE_KEYS
            assert data["calls"], case.id
            for call in data["calls"]:
                assert set(call) == CALL_KEYS | OPTIONAL_CALL_KEYS
                assert call["provider"] == "custom"
            text = path.read_text()
            # The prompt (which embeds the diff) is not stored, only its hash.
            assert case.diff.splitlines()[-1] not in text
            # conftest.py sets these fake provider keys; none may leak.
            for key in ("test-google-key", "test-groq-key", "test-internal-secret"):
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
        assert "make eval-record" in capsys.readouterr().err

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
        assert "Precision (exact location) | 0.333" in md
        assert "**Scored 3 of 3 cases.**" in md


class TestPause:
    async def test_waits_between_cases_not_before_or_after(
        self, fixture_cases, cassettes
    ):
        with patch.object(eval_run.asyncio, "sleep", AsyncMock()) as sleep:
            outcomes = await eval_run.run("replay", fixture_cases, cassettes, pause=75)
        assert len(outcomes) == 3
        assert [c.args for c in sleep.await_args_list] == [(75,), (75,)]

    async def test_no_pause_by_default(self, fixture_cases, cassettes):
        with patch.object(eval_run.asyncio, "sleep", AsyncMock()) as sleep:
            await eval_run.run("replay", fixture_cases, cassettes)
        sleep.assert_not_awaited()

    def test_negative_pause_is_rejected(self):
        with pytest.raises(SystemExit):
            eval_run.main(["--replay", "--pause", "-1"])


class TestProviderFilter:
    async def _providers_called(self, provider, fixture_cases):
        """Run live through the real failover chain; note which providers it hit."""
        called = []

        async def fake_call_provider(config, messages, **kwargs):
            called.append(config.provider.value)
            return LLMResponse(
                content='{"findings": []}',
                model_used=f"{config.provider.value}/{config.model}",
                provider=config.provider,
                prompt_tokens=1,
                completion_tokens=1,
            )

        with patch.object(llm_client, "_call_provider", fake_call_provider):
            outcomes = await eval_run.run(
                "live", fixture_cases[:1], Path("unused"), provider=provider
            )
        assert outcomes[0].error is None, outcomes[0].error
        return called, outcomes[0]

    async def test_without_filter_first_provider_in_chain_is_used(self, fixture_cases):
        called, _ = await self._providers_called(None, fixture_cases)
        assert called and set(called) == {"google"}

    async def test_filter_restricts_chain_to_one_provider(self, fixture_cases):
        called, outcome = await self._providers_called("groq", fixture_cases)
        assert called and set(called) == {"groq"}
        assert {c["model_used"].split("/")[0] for c in outcome.calls} == {"groq"}

    async def test_filter_is_undone_after_the_run(self, fixture_cases):
        from services import llm_client as llm_module

        before = list(llm_module.MODEL_CHAIN)
        await self._providers_called("groq", fixture_cases)
        assert llm_module.MODEL_CHAIN == before

    async def test_unknown_provider_is_an_error(self, fixture_cases):
        with pytest.raises(ValueError, match="not configured"):
            await eval_run.run("live", fixture_cases, Path("unused"), provider="nope")

    def test_provider_requires_live(self):
        with pytest.raises(SystemExit):
            eval_run.main(["--replay", "--provider", "groq"])

    async def test_chain_is_restored_when_the_run_raises(self, fixture_cases):
        from services import llm_client as llm_module

        before = list(llm_module.MODEL_CHAIN)

        async def boom(case, cassettes_dir):
            assert [c.provider.value for c in llm_module.MODEL_CHAIN] == ["groq"]
            raise RuntimeError("quota exhausted")

        with patch.object(eval_run, "live_case", boom):
            with pytest.raises(RuntimeError):
                await eval_run.run(
                    "live", fixture_cases, Path("unused"), provider="groq"
                )
        assert llm_module.MODEL_CHAIN == before


def _constant_generate(content: str):
    async def generate(messages, *, user_id=None, **kwargs):
        return LLMResponse(content, "fixture/hand-written", LLMProvider.CUSTOM, 1, 1)

    return generate


def _call(model="groq/m", provider=None):
    call = {
        "prompt_sha256": "0" * 64,
        "response": "{}",
        "model_used": model,
        "prompt_tokens": 1,
        "completion_tokens": 1,
    }
    if provider:
        call["provider"] = provider
    return call


class TestParseFailures:
    async def test_unparseable_reply_makes_the_case_an_error(self, fixture_cases):
        case = next(c for c in fixture_cases if c.id == "sql-injection-fstring")
        with patch.object(
            llm_client, "generate", _constant_generate("I could not do that.")
        ):
            outcome = await eval_run.live_case(case, None)
        assert outcome.parse_failures == 3  # all three analyzers
        assert outcome.error.startswith("ParseFailure")
        report = eval_run.build_report([outcome], "live", "x", False, "d")
        assert report["parse_failures"]["analyzer_runs_failed"] == 3
        assert report["cases_scored"] == 0
        assert report["metrics"]["missed"] == 1  # counted, not dropped

    def test_count_is_unknown_without_analyzer_runs(self):
        assert eval_run.parse_failures({"synthesized_comments": []}) is None
        assert eval_run.parse_failures({"analyzer_runs": {"security": {}}}) is None
        runs = {"a": {"parsed": True}, "b": {"parsed": False}}
        assert eval_run.parse_failures({"analyzer_runs": runs}) == 1

    def test_report_says_unknown_when_code_does_not_report_it(self, fixture_cases):
        outcome = eval_run.CaseOutcome(
            case=fixture_cases[0], calls=[_call()], parse_failures=None
        )
        report = eval_run.build_report([outcome], "replay", "x", False, None)
        assert report["parse_failures"]["analyzer_runs_failed"] is None
        md = eval_run.render_markdown(report)
        assert "Analyzer parse failures | unknown" in md


SQL_RESULT = {
    "synthesized_comments": [
        {
            "file_path": "shop/repository.py",
            "line_number": 22,
            "category": "security",
            "severity": "error",
            "body": "inline",
            "extra_field": "ignored",
        },
        {  # 2 lines past the hunk (20-24): snapped to 24
            "file_path": "shop/repository.py",
            "line_number": 26,
            "category": "quality",
            "severity": "info",
            "body": "near the hunk",
        },
        {  # far from any hunk: becomes a file-level note
            "file_path": "shop/repository.py",
            "line_number": 90,
            "category": "quality",
            "severity": "info",
            "body": "far away",
        },
        {"file_path": "shop/repository.py", "line_number": 22, "body": ""},
    ]
}


class TestPostProcessing:
    def _diff(self):
        return load_cases(CASES_DIR, {"sql-injection-fstring"})[0].diff

    def test_router_steps_are_applied(self):
        raw, posted, steps, anchoring = eval_run.postprocess(SQL_RESULT, self._diff())
        assert steps == [
            "drop_empty_body",
            "review_comment_validation",
            "anchor_comments",
        ]
        assert [f["line_number"] for f in raw] == [22, 26, 90]
        assert [f["line_number"] for f in posted] == [22, 24, 0]
        assert anchoring == {"anchored": 1, "snapped": 1, "unanchored": 1}
        assert "extra_field" not in posted[0]

    def test_without_anchoring_module_comments_are_not_moved(self):
        # Code without services.comment_anchoring (e.g. the pre-fix
        # baseline) posted comments at the model's line.
        with patch.dict("sys.modules", {"services.comment_anchoring": None}):
            raw, posted, steps, anchoring = eval_run.postprocess(
                SQL_RESULT, self._diff()
            )
        assert "anchor_comments" not in steps
        assert anchoring is None
        assert [f["line_number"] for f in posted] == [22, 26, 90]

    async def test_report_records_post_processing(self, fixture_cases, cassettes):
        report = await _replay_report(fixture_cases, cassettes)
        assert report["post_processing"] == [
            "anchor_comments",
            "drop_empty_body",
            "review_comment_validation",
        ]
        # The fixture's line-40 finding is posted as a file-level note.
        assert report["anchoring"]["unanchored"] == 1


class TestPartialResults:
    def _break_one(self, cassettes, case_id="clean-docstring"):
        path = cassettes / f"{case_id}.json"
        data = json.loads(path.read_text())
        data["case_sha256"] = "0" * 64
        path.write_text(json.dumps(data))

    def _main(self, cassettes, results, *extra):
        return eval_run.main(
            [
                "--replay",
                "--cassettes-dir",
                str(cassettes),
                "--only",
                ",".join(sorted(FIXTURE_IDS)),
                "--results-dir",
                str(results),
                *extra,
            ]
        )

    async def test_refuses_to_write_when_a_case_errored(
        self, cassettes, tmp_path, capsys
    ):
        self._break_one(cassettes)
        results = tmp_path / "results"
        code = await asyncio.to_thread(self._main, cassettes, results)
        assert code == 1
        assert not results.exists()
        err = capsys.readouterr().err
        assert "Scored 2 of 3 cases" in err
        assert "--allow-partial" in err

    async def test_allow_partial_writes_and_counts_the_error(self, cassettes, tmp_path):
        self._break_one(cassettes)
        results = tmp_path / "results"
        code = await asyncio.to_thread(
            self._main, cassettes, results, "--allow-partial", "--results-name", "p"
        )
        assert code == 1
        report = json.loads((results / "p.json").read_text())
        assert report["cases_scored"] == 2
        assert report["run_flags"]["allow_partial"] is True
        # clean-docstring errored, so it counts against the clean-diff rate
        assert report["metrics"]["clean_false_positive_rate"] == 1.0
        assert "Scored 2 of 3 cases" in (results / "p.md").read_text()


class TestProvenance:
    async def test_replay_keeps_recording_date_from_cassettes(
        self, fixture_cases, cassettes
    ):
        report = await _replay_report(fixture_cases, cassettes)
        assert report["date_source"] == "cassettes"
        assert report["date_utc"].endswith("Z")

    async def test_replay_of_older_cassettes_still_works(
        self, fixture_cases, cassettes
    ):
        # Cassettes from before provider and recorded_utc were stored.
        for path in cassettes.glob("*.json"):
            data = json.loads(path.read_text())
            del data["recorded_utc"]
            for call in data["calls"]:
                del call["provider"]
            path.write_text(json.dumps(data))
        report = await _replay_report(fixture_cases, cassettes)
        assert report["errors"] == {}
        assert report["date_utc"] is None
        assert report["date_source"] == "not stored in cassettes"

    def test_latency_is_marked_not_comparable(self, fixture_cases):
        outcome = eval_run.CaseOutcome(
            case=fixture_cases[0], calls=[_call(provider="groq")], parse_failures=0
        )
        report = eval_run.build_report([outcome], "live", "x", False, "d")
        assert report["providers_used"] == ["groq"]
        assert "same providers" in report["latency_ms"]["note"]

    def test_run_flags_are_recorded(self):
        flags = {"pause": 75.0, "provider": "groq"}
        report = eval_run.build_report([], "live", "x", False, "d", flags)
        assert report["run_flags"] == flags

    def test_case_set_hash_changes_with_labels(self, fixture_cases):
        before = eval_run.case_set_sha256(fixture_cases)
        changed = [
            replace(c, expected=[]) if c.id == "sql-injection-fstring" else c
            for c in fixture_cases
        ]
        assert eval_run.case_set_sha256(changed) != before
        assert eval_run.case_set_sha256(list(fixture_cases)) == before

    def test_git_state_counts_untracked_files(self, tmp_path, monkeypatch):
        cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run([*cmd, "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "a.txt").write_text("a")
        subprocess.run([*cmd, "add", "a.txt"], cwd=tmp_path, check=True)
        subprocess.run([*cmd, "commit", "-qm", "a"], cwd=tmp_path, check=True)
        monkeypatch.chdir(tmp_path)
        assert eval_run.git_state()[1] is False
        (tmp_path / "new.txt").write_text("untracked")
        assert eval_run.git_state()[1] is True
