"""
Compare two single runs of the same code, case by case, to show noise.

    uv run python -m scripts.eval_noise RUN1.json RUN2.json

RUN1 and RUN2 are results JSONs written by ``evals.run --results-dir`` for
two live runs of identical code. Only cases scored in both runs are
compared, so a case that errored in either run (for example when a quota ran
out) is left out rather than counted as missed. The report says how many of
those cases changed, at three levels of detail, and totals a few counts over
them for each run.

The README's run-to-run variance paragraph is this script's output for
``after-fixes.json`` and ``dev-rerun.json``. Exits 0 when a report was
printed, 2 when an input can't be read.
"""

import argparse
import json
import sys
from pathlib import Path

from evals.run import case_findings_key, case_scores_key
from scripts.eval_compare import BLOCKING_SEVERITIES


def _full_key(case: dict) -> list[str]:
    """Posted findings including the comment text."""
    return sorted(json.dumps(f, sort_keys=True) for f in case["posted_findings"])


def _scored(report: dict) -> dict[str, dict]:
    return {c["id"]: c for c in report["cases"] if not c.get("error")}


def compare(run1: dict, run2: dict) -> dict:
    a, b = _scored(run1), _scored(run2)
    common = [cid for cid in a if cid in b]

    def changed(key) -> list[str]:
        return [cid for cid in common if key(a[cid]) != key(b[cid])]

    def totals(cases: dict) -> dict[str, int]:
        picked = [cases[cid] for cid in common]
        clean = [c for c in picked if c["clean"]]
        return {
            "exact matches": sum(c["matched"] for c in picked),
            "location-tolerant matches": sum(c["matched"] + c["near"] for c in picked),
            "findings posted": sum(c["findings"] for c in picked),
            "findings on clean diffs": sum(c["findings"] for c in clean),
            "clean diffs with a finding": sum(1 for c in clean if c["findings"]),
            "findings on clean diffs at critical or error severity": sum(
                1
                for c in clean
                for f in c["posted_findings"]
                if f.get("severity") in BLOCKING_SEVERITIES
            ),
        }

    return {
        "case_count": len(run1["cases"]),
        "common": common,
        "changed_scores": changed(case_scores_key),
        "changed_findings": changed(case_findings_key),
        "changed_text": changed(_full_key),
        "totals": (totals(a), totals(b)),
    }


def render(result: dict, name1: str, name2: str) -> str:
    n = len(result["common"])
    t1, t2 = result["totals"]
    lines = [
        f"Cases scored in both runs: {n} of {result['case_count']}.",
        "",
        "Cases whose output differs between the runs:",
        f"- per-case scores (findings, matched, near, partial, missed, extra): "
        f"{len(result['changed_scores'])} of {n}",
        f"- posted findings by file, line, category and severity: "
        f"{len(result['changed_findings'])} of {n}",
        f"- posted findings including the comment text: "
        f"{len(result['changed_text'])} of {n}",
        "",
        f"| Over the {n} common cases | {name1} | {name2} |",
        "|---|---|---|",
    ]
    lines += [f"| {label} | {t1[label]} | {t2[label]} |" for label in t1]
    lines += ["", "Cases with different scores: " + ", ".join(result["changed_scores"])]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("run1", type=Path)
    parser.add_argument("run2", type=Path)
    args = parser.parse_args(argv)
    try:
        run1, run2 = (json.loads(p.read_text()) for p in (args.run1, args.run2))
        result = compare(run1, run2)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Can't compare: {exc}", file=sys.stderr)
        return 2
    print(render(result, args.run1.name, args.run2.name), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
