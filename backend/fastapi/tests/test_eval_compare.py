"""
Tests for scripts/eval_compare.py, the before/after report the CI eval job
posts, and for the README table that report generates.
"""

import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from evals import run as eval_run
from evals.cases import CASES_DIR, load_cases
from scripts import eval_compare

FASTAPI_DIR = Path(__file__).resolve().parent.parent
RESULTS = FASTAPI_DIR / "evals" / "results"
CASSETTES = FASTAPI_DIR / "evals" / "cassettes"
README = FASTAPI_DIR.parent.parent / "README.md"


@pytest.fixture(scope="module")
def baseline():
    return json.loads((RESULTS / "baseline-pre-fix.json").read_text())


@pytest.fixture(scope="module")
def after():
    return json.loads((RESULTS / "after-fixes.json").read_text())


def _row(table: str, label: str) -> list[str]:
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[0] == label:
            return cells[1:]
    raise AssertionError(f"no row {label!r}")


def test_table_values_come_from_the_results_files(baseline, after):
    table = eval_compare.delta_table(baseline, after)
    assert _row(table, "Recall, exact line") == [
        "0.556 (10/18)",
        "1.000 (18/18)",
        "+0.444",
    ]
    assert _row(table, "Precision, exact location") == [
        "0.066 (10/152)",
        "0.281 (18/64)",
        "+0.215",
    ]
    assert _row(table, "False-positive rate on clean diffs") == [
        "1.000 (9/9)",
        "1.000 (9/9)",
        "no change",
    ]
    assert _row(table, "Findings on clean diffs") == ["42", "16", "-26"]
    assert _row(table, "Findings on clean diffs at critical or error severity") == [
        "1",
        "0",
        "-1",
    ]
    assert _row(table, "Analyzer parse failures") == [
        "not reported by this code",
        "0",
        "n/a",
    ]
    assert _row(table, "Anchoring (anchored / snapped / file-level)") == [
        "not applied",
        "64 / 0 / 0",
        "n/a",
    ]


def test_readme_table_is_the_generated_table(baseline, after):
    """Every number in the README's before/after table traces to the JSONs."""
    expected = eval_compare.delta_table(
        baseline, after, "Before (pre-fix)", "After (dev)"
    )
    assert expected in README.read_text()


def test_identical_runs_report_no_change(after):
    report = eval_compare.render(after, copy.deepcopy(after))
    assert report.startswith(eval_compare.MARKER)
    assert "**No metric changed**" in report
    assert "differs between the two runs" not in report
    assert "| Recall, exact line | 1.000 (18/18) | 1.000 (18/18) | no change |" in (
        report
    )
    # Nothing changed, so there is no difference to call noise.
    assert eval_compare.SINGLE_RUN_NOTE not in report


def test_changed_metrics_are_listed_with_deltas(after):
    current = copy.deepcopy(after)
    m = current["metrics"]
    m["matched"], m["recall"] = 17, 17 / 18
    m["precision"] = 17 / 64
    current["harness_sha256"] = "0" * 64
    report = eval_compare.render(after, current)
    assert "**2 metric(s) changed**" in report
    assert "Recall, exact line; Precision, exact location." in report
    assert "| Recall, exact line | 1.000 (18/18) | 0.944 (17/18) | -0.056 |" in report
    assert "The harness code (`evals/*.py`) differs between the two runs." in report
    assert eval_compare.SINGLE_RUN_NOTE in report


def test_errors_that_are_not_cassette_misses_are_reported(after):
    current = copy.deepcopy(after)
    current["errors"] = {"missing-await": "ParseFailure: 1 analyzer run(s) ..."}
    report = eval_compare.render(after, current)
    assert "**1 case(s) errored**" in report
    assert "- missing-await: ParseFailure" in report
    assert "| Metric |" in report  # still scored and compared


def _multi(after: dict, matched_per_run: list[int]) -> dict:
    """A multi-run results file: after-fixes with ``matched`` set per run."""
    reports = []
    for matched in matched_per_run:
        r = copy.deepcopy(after)
        m = r["metrics"]
        m["matched"], m["recall"] = matched, matched / m["expected_total"]
        m["precision"] = matched / m["findings_total"]
        reports.append(r)
    return eval_run.build_repeat_report(reports)


def test_within_noise_rule():
    # Either side's mean inside the other side's min-max.
    assert eval_compare.within_noise([16, 18, 17], [17, 18, 18])  # 17 in 17-18
    assert eval_compare.within_noise([17, 17, 17], [16, 17, 19])  # 17 in 16-19
    assert not eval_compare.within_noise([18, 18, 18], [16, 16, 17])


def test_multi_run_change_inside_the_spread_is_within_noise(after):
    base, current = _multi(after, [16, 18, 17]), _multi(after, [17, 18, 18])
    report = eval_compare.render(base, current, "ref")
    assert "**2 metric(s) changed** against ref" in report
    assert "2 of them within noise" in report
    assert eval_compare.SINGLE_RUN_NOTE not in report
    assert (
        "| Recall, exact line | 0.944 (0.889–1.000) | 0.981 (0.944–1.000) "
        "| +0.037 | within noise |"
    ) in report
    assert "| Findings posted | 64 (64–64) | 64 (64–64) | no change |  |" in report
    assert "| 64 / 0 / 0 | 64 / 0 / 0 | no change |" in report  # same every run
    assert "ref: commit `01095e380ba9`, replay, 3 runs" in report


def test_multi_run_change_outside_the_spread_is_flagged(after):
    base, current = _multi(after, [18, 18, 18]), _multi(after, [16, 16, 17])
    report = eval_compare.render(base, current)
    assert "**2 metric(s) changed**" in report
    assert "None of them is within noise" in report
    assert (
        "| Recall, exact line | 1.000 (1.000–1.000) | 0.907 (0.889–0.944) "
        "| -0.093 | outside noise |"
    ) in report


def test_single_run_against_multi_run_gets_no_noise_verdict(after):
    current = _multi(after, [16, 18, 17])
    report = eval_compare.render(after, current)
    assert eval_compare.SINGLE_RUN_NOTE in report
    assert "| 1.000 (18/18) | 0.944 (0.889–1.000) | -0.056 | single run |" in report


def test_cassette_miss_in_a_later_run_is_reported(after):
    current = _multi(after, [18, 18])
    current["runs"][1]["errors"] = {"missing-await": "CassetteMiss: no cassette"}
    assert eval_compare.cassette_misses(current) == ["missing-await"]
    assert "**Prompt changed" in eval_compare.render(after, current)


def _replay(cassettes: Path, ids: set[str]) -> dict:
    cases = load_cases(CASES_DIR, ids)
    outcomes = asyncio.run(eval_run.run("replay", cases, cassettes))
    return eval_run.build_report(outcomes, "replay", "abc", False, None)


def _record_with_reply(cassettes: Path, case_id: str, reply: str) -> None:
    """Record ``case_id`` from the current prompts, every call answered ``reply``."""
    from services.llm_client import LLMProvider, LLMResponse, llm_client

    async def generate(messages, *, user_id=None, **kwargs):
        return LLMResponse(
            content=reply,
            model_used="fixture/hand-written",
            provider=LLMProvider.CUSTOM,
            prompt_tokens=1,
            completion_tokens=1,
        )

    (case,) = load_cases(CASES_DIR, {case_id})
    with patch.object(llm_client, "generate", generate):
        outcome = asyncio.run(eval_run.live_case(case, cassettes))
    assert outcome.error is None, outcome.error


def test_prompt_change_reports_cassette_miss_and_no_metrics(tmp_path, after):
    """A changed prompt has no recorded response: say so, don't score."""
    case_id = "missing-await"
    cassette = json.loads((CASSETTES / f"{case_id}.json").read_text())
    for call in cassette["calls"]:
        call["prompt_sha256"] = "f" * 64  # as if the agent's prompt changed
    (tmp_path / f"{case_id}.json").write_text(json.dumps(cassette))
    # A cassette that matches today's prompts, whether or not the committed
    # ones have been re-recorded since the last prompt change.
    _record_with_reply(tmp_path, "xss-innerhtml", '{"findings": []}')

    current = _replay(tmp_path, {case_id, "xss-innerhtml"})
    assert eval_compare.cassette_misses(current) == [case_id]

    report = eval_compare.render(after, current)
    assert "**Prompt changed: replay can't measure this PR.**" in report
    assert "1 of 2 cases" in report
    assert eval_compare.RECORD_COMMAND in report
    assert f"Cases without a recording: {case_id}" in report
    assert "| Metric |" not in report


def test_missing_cassette_counts_as_a_miss(tmp_path, after):
    current = _replay(tmp_path, {"missing-await"})
    assert eval_compare.cassette_misses(current) == ["missing-await"]
    assert "Prompt changed" in eval_compare.render(after, current)


def test_committed_cassettes_replay_to_the_reference_run():
    """The CI reference (after-a7.json) is what the committed cassettes give."""
    reference = json.loads((RESULTS / "after-a7.json").read_text())
    current = _replay(CASSETTES, None)
    assert current["errors"] == {}
    report = eval_compare.render(reference, current, "after-a7.json")
    assert "**No metric changed** against after-a7.json." in report
    assert [c["posted_findings"] for c in current["cases"]] == [
        c["posted_findings"] for c in reference["cases"]
    ]


def test_main_prints_report_and_rejects_bad_input(tmp_path, capsys):
    base = str(RESULTS / "after-fixes.json")
    assert eval_compare.main([base, base]) == 0
    assert "**No metric changed**" in capsys.readouterr().out

    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert eval_compare.main([base, str(bad)]) == 2
    assert "not an eval results file" in capsys.readouterr().err
    assert eval_compare.main([base, str(tmp_path / "absent.json")]) == 2
