"""
Compare two review-eval results files and print a markdown report.

    uv run python -m scripts.eval_compare BASE.json CURRENT.json

BASE and CURRENT are results JSONs written by ``evals.run --results-dir``.
The report has a status line, the provenance of both runs and a table of
each metric in both runs with the change. It is what the CI eval job posts
on a pull request.

If CURRENT has cases that errored with a cassette miss, the agent's prompts
(or a case's diff) changed, so replay can't score this code: the report says
so and shows no metrics, because the missed cases would count as misses.

Latency is not compared: replay reports the latency stored in the cassettes,
and recorded latency depends on the provider chain and quotas.

Run-to-run noise: when either file holds several runs (``evals.run --live
--repeat N``), each metric is shown as its mean and min-max across runs.
When both sides have at least 2 runs, a changed metric is marked "within
noise" if either side's mean falls inside the other side's min-max. With a
single run on either side there is no spread to compare against, so a
changed report says that differences of a few findings may be noise.

This lives outside ``evals/`` on purpose: ``evals/*.py`` is hashed into the
results' ``harness_sha256``, and this report doesn't change scoring.
Exits 0 when a report was printed, 2 when an input can't be read.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MARKER = "<!-- devmind-eval-report -->"
RECORD_COMMAND = 'make eval-record EVAL_ARGS="--provider groq --pause 75"'
MISS_PREFIX = "CassetteMiss:"
BLOCKING_SEVERITIES = ("critical", "error")
SINGLE_RUN_NOTE = (
    "Single run: differences of a few findings may be noise. Two live runs "
    "of identical code differ from each other (see the README, Review "
    "quality); record several runs with `--repeat 3` to measure the spread."
)


def _ratio(m: dict, value: str, num: tuple[str, ...], den: str) -> dict:
    if m.get(value) is None or any(m.get(k) is None for k in (*num, den)):
        return {"value": None, "text": "n/a"}
    n = sum(m[k] for k in num)
    return {"value": m[value], "text": f"{m[value]:.3f} ({n}/{m[den]})"}


def _count(value: int | None) -> dict:
    return {"value": value, "text": "n/a" if value is None else str(value)}


def clean_blocking_findings(report: dict) -> int | None:
    """Posted findings at critical or error severity on clean diffs."""
    cases = report.get("cases")
    if not cases or any("posted_findings" not in c for c in cases):
        return None
    return sum(
        1
        for c in cases
        if c.get("clean")
        for f in c["posted_findings"]
        if f.get("severity") in BLOCKING_SEVERITIES
    )


def rows(report: dict) -> list[tuple[str, dict]]:
    """(label, {value, text}) for each compared metric, in display order."""
    m = report.get("metrics", {})
    pf = report.get("parse_failures") or {}
    anch = report.get("anchoring")
    failed = pf.get("analyzer_runs_failed")
    clean_fp_num = ("clean_cases_with_findings", "clean_cases_errored")
    return [
        ("Recall, exact line", _ratio(m, "recall", ("matched",), "expected_total")),
        (
            "Precision, exact location",
            _ratio(m, "precision", ("matched",), "findings_total"),
        ),
        (
            "Precision, duplicates collapsed",
            _ratio(m, "precision_dedup", ("matched_dedup",), "unique_findings_total"),
        ),
        (
            "Precision, location-tolerant",
            _ratio(m, "precision_tolerant", ("matched", "near"), "findings_total"),
        ),
        (
            "Recall, location-tolerant",
            _ratio(m, "recall_tolerant", ("matched", "near"), "expected_total"),
        ),
        (
            "False-positive rate on clean diffs",
            _ratio(m, "clean_false_positive_rate", clean_fp_num, "clean_cases"),
        ),
        ("Findings on clean diffs", _count(m.get("clean_findings_total"))),
        (
            "Findings on clean diffs at critical or error severity",
            _count(clean_blocking_findings(report)),
        ),
        ("Findings posted", _count(m.get("findings_total"))),
        (
            "Valid-line rate (agent output, before anchoring)",
            _ratio(
                m, "valid_line_rate", ("valid_line_findings",), "raw_findings_total"
            ),
        ),
        (
            "Analyzer parse failures",
            {
                "value": failed,
                "text": "not reported by this code" if failed is None else str(failed),
            },
        ),
        (
            "Anchoring (anchored / snapped / file-level)",
            {
                "value": (
                    None
                    if not anch
                    else (anch["anchored"], anch["snapped"], anch["unanchored"])
                ),
                "text": (
                    "not applied"
                    if not anch
                    else f"{anch['anchored']} / {anch['snapped']} / "
                    f"{anch['unanchored']}"
                ),
            },
        ),
        (
            "Cases scored",
            {
                "value": report.get("cases_scored"),
                "text": f"{report.get('cases_scored')} of {report.get('case_count')}",
            },
        ),
    ]


def runs_of(report: dict) -> list[dict]:
    """Each run's fields: the ``runs`` of a multi-run file, else the file."""
    return report.get("runs") or [report]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def run_rows(report: dict) -> list[tuple[str, list[dict]]]:
    """(label, [{value, text} per run]) for each compared metric."""
    per_run = [rows(r) for r in runs_of(report)]
    return [
        (label, [r[i][1] for r in per_run]) for i, (label, _) in enumerate(per_run[0])
    ]


def _numbers(cells: list[dict]) -> list[float] | None:
    values = [c["value"] for c in cells]
    return values if all(_is_number(v) for v in values) else None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def within_noise(base: list[float], current: list[float]) -> bool:
    """Either side's mean lies inside the other side's min-max."""
    mb, mc = _mean(base), _mean(current)
    return min(current) <= mb <= max(current) or min(base) <= mc <= max(base)


def _num_text(value: float, ratio: bool) -> str:
    if ratio:
        return f"{value:.3f}"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _spread_text(cells: list[dict]) -> str:
    if len(cells) == 1:
        return cells[0]["text"]
    values = _numbers(cells)
    if values is None:
        return "; ".join(dict.fromkeys(c["text"] for c in cells))
    ratio = any(isinstance(v, float) for v in values)
    return (
        f"{_num_text(_mean(values), ratio)} "
        f"({_num_text(min(values), ratio)}–{_num_text(max(values), ratio)})"
    )


def _summary(cells: list[dict]) -> Any:
    """What two sides are compared on: the mean, or the per-run values."""
    values = _numbers(cells)
    if values is None:
        return [c["value"] for c in cells]
    return _mean(values)


def _change(before: Any, after: Any) -> str:
    if before == after:
        return "no change"
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        if isinstance(before, int) and isinstance(after, int):
            return f"{after - before:+d}"
        return f"{after - before:+.3f}"
    return "n/a"


def delta_table(
    base: dict, current: dict, base_label: str = "Before", cur_label: str = "After"
) -> str:
    lines = [
        f"| Metric | {base_label} | {cur_label} | Change |",
        "|---|---|---|---|",
    ]
    for (label, b), (_, c) in zip(rows(base), rows(current)):
        lines.append(
            f"| {label} | {b['text']} | {c['text']} | "
            f"{_change(b['value'], c['value'])} |"
        )
    return "\n".join(lines) + "\n"


def spread_table(
    base: dict, current: dict, base_label: str = "Before", cur_label: str = "After"
) -> str:
    """Mean (min–max) per metric, for files with several runs."""
    both = len(runs_of(base)) > 1 and len(runs_of(current)) > 1
    lines = [
        f"| Metric | {base_label}, mean (min–max) | {cur_label}, mean (min–max) "
        "| Change in mean | Noise check |",
        "|---|---|---|---|---|",
    ]
    for (label, b), (_, c) in zip(run_rows(base), run_rows(current)):
        bn, cn = _numbers(b), _numbers(c)
        change = "no change" if _summary(b) == _summary(c) else "n/a"
        if bn is not None and cn is not None and change != "no change":
            delta = _mean(cn) - _mean(bn)
            ratio = any(isinstance(v, float) for v in bn + cn)
            change = f"{'+' if delta > 0 else '-'}{_num_text(abs(delta), ratio)}"
        if change == "no change":
            noise = ""
        elif bn is None or cn is None:
            noise = "n/a"
        elif not both:
            noise = "single run"
        else:
            noise = "within noise" if within_noise(bn, cn) else "outside noise"
        lines.append(
            f"| {label} | {_spread_text(b)} | {_spread_text(c)} | {change} "
            f"| {noise} |"
        )
    return "\n".join(lines) + "\n"


def changed_metrics(base: dict, current: dict) -> list[str]:
    return [
        label
        for (label, b), (_, c) in zip(run_rows(base), run_rows(current))
        if _summary(b) != _summary(c)
    ]


def noise_metrics(base: dict, current: dict) -> list[str] | None:
    """Changed metrics within noise, or None unless both sides have 2+ runs."""
    if len(runs_of(base)) < 2 or len(runs_of(current)) < 2:
        return None
    changed = set(changed_metrics(base, current))
    out = []
    for (label, b), (_, c) in zip(run_rows(base), run_rows(current)):
        bn, cn = _numbers(b), _numbers(c)
        if label in changed and bn and cn and within_noise(bn, cn):
            out.append(label)
    return out


def _errors(report: dict) -> dict[str, str]:
    """Errors of every run: ``case`` for one run, ``case (run i)`` for several."""
    runs = runs_of(report)
    if len(runs) == 1:
        return dict(report.get("errors") or {})
    return {
        f"{cid} (run {i})": err
        for i, r in enumerate(runs, 1)
        for cid, err in (r.get("errors") or {}).items()
    }


def cassette_misses(report: dict) -> list[str]:
    return sorted(
        {
            cid
            for r in runs_of(report)
            for cid, err in (r.get("errors") or {}).items()
            if err.startswith(MISS_PREFIX)
        }
    )


def _provenance(report: dict, name: str) -> str:
    commit = (report.get("commit") or "unknown")[:12]
    dirty = " (uncommitted files)" if report.get("dirty_worktree") else ""
    models = ", ".join(report.get("models_used") or []) or "none"
    runs = len(runs_of(report))
    run_text = f", {runs} runs" if runs > 1 else ", 1 run"
    return (
        f"- {name}: commit `{commit}`{dirty}, {report.get('mode')}{run_text}, "
        f"models {models}, {report.get('case_count')} cases, "
        f"harness `{(report.get('harness_sha256') or '')[:8]}`, "
        f"case set `{(report.get('case_set_sha256') or '')[:8]}`"
    )


def render(
    base: dict,
    current: dict,
    base_name: str = "base",
    cur_name: str = "this PR",
) -> str:
    """The full markdown report, starting with the comment marker."""
    out = [MARKER, "## Review eval (replay)", ""]
    misses = cassette_misses(current)
    other = {
        key: err
        for key, err in _errors(current).items()
        if not err.startswith(MISS_PREFIX)
    }
    if misses:
        out += [
            "**Prompt changed: replay can't measure this PR.** "
            f"{len(misses)} of {current.get('case_count')} cases have no "
            "recorded response for the prompts this code sends (or the case "
            "diff changed). Re-record with "
            f"`{RECORD_COMMAND}` (needs provider keys) and commit the "
            "cassettes and results.",
            "",
            f"Cases without a recording: {', '.join(misses)}",
        ]
        if other:
            out += ["", "Other errors:"]
            out += [f"- {cid}: {err}" for cid, err in sorted(other.items())]
        out += ["", _provenance(base, base_name), _provenance(current, cur_name)]
        return "\n".join(out) + "\n"

    changed = changed_metrics(base, current)
    multi = len(runs_of(base)) > 1 or len(runs_of(current)) > 1
    if other:
        out.append(
            f"**{len(other)} case(s) errored** in replay; errored cases count "
            "as missed (defects) or as false positives (clean diffs)."
        )
        out += [f"- {cid}: {err}" for cid, err in sorted(other.items())]
        out.append("")
    if changed:
        out.append(
            f"**{len(changed)} metric(s) changed** against {base_name}: "
            + "; ".join(changed)
            + "."
        )
        noise = noise_metrics(base, current)
        if noise is None:
            out.append(SINGLE_RUN_NOTE)
        elif noise:
            out.append(
                f"{len(noise)} of them within noise (either side's mean is "
                "inside the other side's min–max): " + "; ".join(noise) + "."
            )
        else:
            out.append(
                "None of them is within noise (neither side's mean is inside "
                "the other side's min–max)."
            )
    else:
        out.append(f"**No metric changed** against {base_name}.")
    for key, what in (
        ("harness_sha256", "The harness code (`evals/*.py`)"),
        ("case_set_sha256", "The case set (diffs or labels)"),
    ):
        if base.get(key) != current.get(key):
            out.append(f"{what} differs between the two runs.")
    out += [
        "",
        (
            spread_table(base, current, base_name, cur_name)
            if multi
            else delta_table(base, current, base_name, cur_name)
        ),
        "Latency is not compared: replay reports the latency stored in the "
        "cassettes.",
        "",
        _provenance(base, base_name),
        _provenance(current, cur_name),
    ]
    return "\n".join(out) + "\n"


def _load(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or "metrics" not in data:
        raise ValueError(f"{path}: not an eval results file")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("base", type=Path, help="results JSON to compare against")
    parser.add_argument("current", type=Path, help="results JSON of this run")
    parser.add_argument("--base-name", default="base")
    parser.add_argument("--current-name", default="this PR")
    args = parser.parse_args(argv)
    try:
        base, current = _load(args.base), _load(args.current)
    except (OSError, ValueError) as exc:
        print(f"Can't compare: {exc}", file=sys.stderr)
        return 2
    print(render(base, current, args.base_name, args.current_name), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
