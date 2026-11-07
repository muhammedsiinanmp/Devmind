"""
Tests for scripts/eval_noise.py and the README's run-to-run variance numbers.
"""

import copy
import json
from pathlib import Path

from scripts import eval_noise

FASTAPI_DIR = Path(__file__).resolve().parent.parent
RESULTS = FASTAPI_DIR / "evals" / "results"
README = FASTAPI_DIR.parent.parent / "README.md"


def _load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text())


def test_readme_variance_output_is_generated_from_the_results_files():
    """Every number in the README's variance block traces to the two JSONs."""
    result = eval_noise.compare(_load("after-fixes.json"), _load("dev-rerun.json"))
    block = eval_noise.render(result, "after-fixes.json", "dev-rerun.json")
    assert block in README.read_text()


def test_dev_runs_compare_on_the_cases_both_scored():
    result = eval_noise.compare(_load("after-fixes.json"), _load("dev-rerun.json"))
    assert len(result["common"]) == 23
    assert "xss-innerhtml" not in result["common"]  # errored in the rerun
    assert len(result["changed_scores"]) == 11
    first, second = result["totals"]
    assert first["exact matches"] == second["exact matches"] == 14
    assert (first["findings posted"], second["findings posted"]) == (59, 58)


def _report(cases: list[dict]) -> dict:
    return {"cases": cases}


def _case(cid, findings=(), error=None, clean=False, matched=0):
    posted = [
        {"file_path": "a.py", "line_number": n, "category": "quality"}
        | {"severity": sev, "body": body}
        for n, sev, body in findings
    ]
    return {
        "id": cid,
        "clean": clean,
        "error": error,
        "findings": len(posted),
        "matched": matched,
        "near": 0,
        "partial": 0,
        "missed": 0,
        "extra": len(posted) - matched,
        "posted_findings": posted,
    }


def test_levels_of_change_and_errored_cases():
    run1 = _report(
        [
            _case("same", [(1, "warning", "x")]),
            _case("text-only", [(1, "warning", "x")]),
            _case("moved", [(1, "warning", "x")]),
            _case("errored", [(1, "warning", "x")]),
            _case("clean", clean=True),
        ]
    )
    run2 = copy.deepcopy(run1)
    cases = {c["id"]: c for c in run2["cases"]}
    cases["text-only"]["posted_findings"][0]["body"] = "y"
    cases["moved"]["posted_findings"][0]["line_number"] = 2
    cases["errored"]["error"] = "AllProvidersDownError: quota"
    cases["clean"].update(
        _case("clean", [(3, "error", "z")], clean=True)
    )  # a new blocking finding on a clean diff

    result = eval_noise.compare(run1, run2)
    assert result["common"] == ["same", "text-only", "moved", "clean"]
    assert result["changed_scores"] == ["clean"]
    assert result["changed_findings"] == ["moved", "clean"]
    assert result["changed_text"] == ["text-only", "moved", "clean"]
    first, second = result["totals"]
    key = "findings on clean diffs at critical or error severity"
    assert (first[key], second[key]) == (0, 1)
    assert (
        first["clean diffs with a finding"],
        second["clean diffs with a finding"],
    ) == (
        0,
        1,
    )
    text = eval_noise.render(result, "a", "b")
    assert "Cases scored in both runs: 4 of 5." in text
    assert "including the comment text: 3 of 4" in text


def test_main_rejects_unreadable_input(tmp_path, capsys):
    good = str(RESULTS / "after-fixes.json")
    assert eval_noise.main([good, str(RESULTS / "dev-rerun.json")]) == 0
    assert "Cases scored in both runs: 23 of 27." in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert eval_noise.main([good, str(bad)]) == 2
    assert "Can't compare" in capsys.readouterr().err
