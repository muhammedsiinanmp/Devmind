"""
Run the review agent over the labeled eval cases and score it.

    uv run python -m evals.run --replay              # offline, from cassettes
    uv run python -m evals.run --live --record \\
        --results-dir evals/results                  # real providers
    uv run python -m evals.run --live --record --repeat 3 ...  # 3 runs per case

With ``--repeat N`` (N > 1) each case is run N times, one full pass over the
cases per run, and recorded to ``<case>.<i>.json`` (i = 1..N). Replay
replays every recorded run when the cassettes directory holds numbered
cassettes. A multi-run report shows each metric's mean and min-max across
runs and, per case, how many runs agree.

Runs ``run_review_agent`` directly, without the router's database/RAG step,
so no Postgres is needed. ``llm_client.generate`` is swapped out: in
replay it serves recorded responses, in live mode it is wrapped so the
responses can be recorded. The only change to the prompts the agent sends is
that the untrusted-data delimiter tag uses a fixed nonce
(EVAL_DELIMITER_NONCE) instead of a random one, so they replay.

The agent's output is then put through the same post-processing the router
applies before posting (see ``postprocess``), so the scores describe what
would be posted.
"""

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from evals.cases import CASES_DIR, Case, load_cases
from evals.cassette import (
    Player,
    Recorder,
    load_cassette,
    save_cassette,
)
from evals.matcher import aggregate, diff_hunks, is_valid_line, match_case

EVALS_DIR = Path(__file__).parent
CASSETTES_DIR = EVALS_DIR / "cassettes"
RESULTS_DIR = EVALS_DIR / "results"
REPO_NAME = "devmind-evals/synthetic"
# Delimiter-tag nonce used for every eval prompt (see _run_agent).
EVAL_DELIMITER_NONCE = "000000000000000000"
LATENCY_NOTE = (
    "Latency depends on the provider chain, quotas and network; compare it "
    "only between runs that used the same providers."
)

# USD per million tokens, keyed by the client's model_used string
# (e.g. "groq/llama-3.3-70b-versatile"). Empty on purpose: add a price only
# from the provider's published pricing. Unpriced runs report cost as null.
PRICES_PER_MTOK: dict[str, dict[str, float]] = {}


@dataclass
class CaseOutcome:
    case: Case
    findings: list[dict] = field(default_factory=list)  # as posted
    raw_findings: list[dict] = field(default_factory=list)  # agent output
    calls: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None
    # Analyzer runs whose reply could not be parsed; None when the agent
    # doesn't report it (no analyzer_runs/parsed in its result).
    parse_failures: int | None = None
    post_processing: list[str] = field(default_factory=list)
    anchoring: dict[str, int] | None = None
    recorded_utc: str | None = None


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def git_state() -> tuple[str, bool]:
    """HEAD commit, and whether there are uncommitted or untracked files."""
    sha = _git("rev-parse", "HEAD") or "unknown"
    dirty = bool(_git("status", "--porcelain"))
    return sha, dirty


def harness_sha256() -> str:
    """Hash of the harness code (evals/*.py), to identify the scorer."""
    h = hashlib.sha256()
    for path in sorted(EVALS_DIR.glob("*.py")):
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def case_set_sha256(cases: list[Case]) -> str:
    """Hash of the case ids, diffs, labels and feedback examples that were scored."""
    payload = [
        {"id": c.id, "diff": c.digest, "expected": [asdict(e) for e in c.expected]}
        # Only cases with examples carry the key, so other hashes are unchanged.
        | ({"feedback": [asdict(f) for f in c.feedback]} if c.feedback else {})
        for c in cases
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=list).encode()
    ).hexdigest()


def parse_failures(result: dict) -> int | None:
    """Count analyzer runs with parsed=False, or None if not reported."""
    runs = result.get("analyzer_runs")
    if not isinstance(runs, dict):
        return None
    flags = [r.get("parsed") for r in runs.values() if isinstance(r, dict)]
    if not flags or any(f is None for f in flags):
        return None
    return sum(1 for f in flags if f is False)


def postprocess(
    result: dict, diff_text: str
) -> tuple[list[dict], list[dict], list[str], dict | None]:
    """Apply the router's pre-posting steps to the agent's comments.

    Mirrors routers/review.py: drop comments without a body, validate each as
    a ReviewComment, then anchor them to diff lines with anchor_comments()
    when services.comment_anchoring exists. Each step is import-guarded so
    the harness also scores older code truthfully (e.g. code without
    anchoring). Returns (raw, posted, steps that ran, anchoring counts).
    """
    raw = [
        dict(c)
        for c in result.get("synthesized_comments", []) or []
        if isinstance(c, dict) and c.get("body")
    ]
    steps = ["drop_empty_body"]
    try:
        from models.review import ReviewComment
    except ImportError:
        return raw, raw, steps, None

    comments = [
        ReviewComment(
            file_path=item.get("file_path", ""),
            line_number=item.get("line_number", 0),
            category=item.get("category", "general"),
            severity=item.get("severity", "info"),
            body=item.get("body", ""),
            suggested_fix=item.get("suggested_fix"),
        )
        for item in raw
    ]
    steps.append("review_comment_validation")

    anchoring = None
    try:
        from services.comment_anchoring import anchor_comments
        from services.code_parser import parse_diff
    except ImportError:
        anchor_comments = None
    if anchor_comments is not None:
        comments, stats = anchor_comments(parse_diff(diff_text), comments)
        steps.append("anchor_comments")
        anchoring = asdict(stats)

    return raw, [c.model_dump() for c in comments], steps, anchoring


def _finish(outcome: CaseOutcome, result: dict) -> None:
    raw, posted, steps, anchoring = postprocess(result, outcome.case.diff)
    outcome.raw_findings = raw
    outcome.findings = posted
    outcome.post_processing = steps
    outcome.anchoring = anchoring
    outcome.parse_failures = parse_failures(result)
    if outcome.parse_failures:
        outcome.error = (
            f"ParseFailure: {outcome.parse_failures} analyzer run(s) "
            "returned a reply that could not be parsed"
        )


def _replay_response(call: dict):
    from services.llm_client import LLMProvider, LLMResponse

    name = call.get("provider") or call["model_used"].split("/", 1)[0]
    try:
        provider = LLMProvider(name)
    except ValueError:
        provider = LLMProvider.CUSTOM
    return LLMResponse(
        content=call["response"],
        model_used=call["model_used"],
        provider=provider,
        prompt_tokens=call["prompt_tokens"],
        completion_tokens=call["completion_tokens"],
    )


async def _run_agent(case: Case, generate) -> dict:
    from agents.review_agent import run_review_agent
    from services import prompt_builder
    from services.llm_client import llm_client

    # Fixed delimiter nonce, so the prompts (and their cassette hashes) are
    # the same on every run; in production each review gets a random one.
    with (
        patch.object(llm_client, "generate", generate),
        patch.object(prompt_builder, "delimiter_nonce", lambda: EVAL_DELIMITER_NONCE),
    ):
        return await run_review_agent(
            diff_text=case.diff,
            repo_full_name=REPO_NAME,
            # The case's feedback examples, given directly: no database.
            feedback=case.feedback_context(),
        )


def cassette_file(case_id: str, run_index: int | None = None) -> str:
    """``<case>.json`` for a single run, ``<case>.<i>.json`` for run i.

    Callers pass ``case.cassette_stem``, so a feedback case run with
    --no-feedback uses ``<case>.no-feedback.json`` / ``<case>.no-feedback.<i>.json``.
    """
    return f"{case_id}.json" if run_index is None else f"{case_id}.{run_index}.json"


def recorded_runs(cassettes_dir: Path) -> list[int]:
    """Run numbers of the numbered cassettes (``<case>.<i>.json``), sorted.

    Empty when the directory holds single-run cassettes (``<case>.json``).
    """
    runs = set()
    for path in cassettes_dir.glob("*.*.json"):
        suffix = path.name[: -len(".json")].rsplit(".", 1)[1]
        if suffix.isdigit():
            runs.add(int(suffix))
    return sorted(runs)


async def replay_case(
    case: Case, cassettes_dir: Path, run_index: int | None = None
) -> CaseOutcome:
    outcome = CaseOutcome(case=case)
    try:
        cassette = load_cassette(
            cassettes_dir / cassette_file(case.cassette_stem, run_index),
            case.id,
            case.digest,
        )
        outcome.latency_ms = cassette["latency_ms"]
        outcome.recorded_utc = cassette.get("recorded_utc")
        player = Player(cassette["calls"], _replay_response)
        result = await _run_agent(case, player)
        outcome.calls = player.calls
        _finish(outcome, result)
    except Exception as exc:  # reported per case; the run continues
        outcome.error = f"{type(exc).__name__}: {exc}"
    return outcome


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def live_case(
    case: Case, cassettes_dir: Path | None, run_index: int | None = None
) -> CaseOutcome:
    from core.config import get_settings
    from services.llm_client import llm_client

    s = get_settings()
    # Every configured key or secret, whatever the provider set is today.
    secrets = [
        str(value)
        for name, value in s.model_dump().items()
        if value and any(t in name for t in ("key", "token", "secret"))
    ]
    recorder = Recorder(llm_client.generate, secrets=secrets)
    outcome = CaseOutcome(case=case, recorded_utc=_now_utc())
    start = time.perf_counter()
    try:
        result = await _run_agent(case, recorder)
    except Exception as exc:  # keep going; the case is reported as an error
        outcome.error = f"{type(exc).__name__}: {exc}"
        return outcome
    outcome.latency_ms = int((time.perf_counter() - start) * 1000)
    outcome.calls = recorder.calls
    # Save before scoring, so a case that fails scoring can still be replayed.
    if cassettes_dir is not None:
        save_cassette(
            cassettes_dir / cassette_file(case.cassette_stem, run_index),
            case.id,
            case.digest,
            recorder.calls,
            outcome.latency_ms,
            recorded_utc=outcome.recorded_utc,
        )
    try:
        _finish(outcome, result)
    except Exception as exc:
        outcome.error = f"{type(exc).__name__}: {exc}"
    return outcome


def _cost(calls: list[dict]) -> float | None:
    total = 0.0
    for call in calls:
        price = PRICES_PER_MTOK.get(call["model_used"])
        if price is None:
            return None
        total += call["prompt_tokens"] * price["input"] / 1e6
        total += call["completion_tokens"] * price["output"] / 1e6
    return round(total, 6)


def _call_provider(call: dict) -> str:
    return call.get("provider") or call["model_used"].split("/", 1)[0]


def _finding_view(f: dict) -> dict:
    keys = ("file_path", "line_number", "category", "severity", "body")
    return {k: f.get(k) for k in keys}


def build_report(
    outcomes: list[CaseOutcome],
    mode: str,
    commit: str,
    dirty: bool,
    date: str | None,
    flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scored = [o for o in outcomes if o.error is None]
    all_calls = [c for o in outcomes for c in o.calls]
    latencies = [o.latency_ms for o in scored]

    if mode == "live":
        date_source = "run"
    else:
        recorded = sorted(o.recorded_utc for o in outcomes if o.recorded_utc)
        date = recorded[-1] if recorded else None
        date_source = "cassettes" if recorded else "not stored in cassettes"

    known = [o.parse_failures for o in outcomes if o.parse_failures is not None]
    unknown = sum(
        1 for o in outcomes if o.parse_failures is None and (o.calls or o.findings)
    )
    steps = sorted({s for o in outcomes for s in o.post_processing})
    anchoring = None
    if any(o.anchoring for o in outcomes):
        anchoring = {
            k: sum((o.anchoring or {}).get(k, 0) for o in outcomes)
            for k in ("anchored", "snapped", "unanchored")
        }

    per_case = []
    for o in outcomes:
        hunks = diff_hunks(o.case.diff)
        lines = {f: set().union(*h) if h else set() for f, h in hunks.items()}
        res = match_case(o.case.expected, o.findings, hunks)
        per_case.append(
            {
                "id": o.case.id,
                "clean": not o.case.expected,
                "error": o.error,
                "expected": len(o.case.expected),
                "findings": len(o.findings),
                "matched": len(res.matched),
                "near": len(res.near),
                "partial": len(res.partial),
                "missed": len(res.missed),
                "extra": len(res.extra),
                "valid_lines": sum(is_valid_line(f, lines) for f in o.raw_findings),
                "parse_failures": o.parse_failures,
                "latency_ms": o.latency_ms,
                "model_calls": len(o.calls),
                "raw_findings": [_finding_view(f) for f in o.raw_findings],
                "posted_findings": [_finding_view(f) for f in o.findings],
            }
        )
    return {
        "mode": mode,
        "commit": commit,
        "dirty_worktree": dirty,
        "date_utc": date,
        "date_source": date_source,
        "run_flags": flags or {},
        "harness_sha256": harness_sha256(),
        "case_set_sha256": case_set_sha256([o.case for o in outcomes]),
        "models_used": sorted({c["model_used"] for c in all_calls}),
        "providers_used": sorted({_call_provider(c) for c in all_calls}),
        "case_count": len(outcomes),
        "cases_scored": len(scored),
        "scored_case_ids": [o.case.id for o in scored],
        "errors": {o.case.id: o.error for o in outcomes if o.error},
        "post_processing": steps,
        "anchoring": anchoring,
        "parse_failures": {
            "analyzer_runs_failed": sum(known) if not unknown else None,
            "cases_unknown": unknown,
            "note": (
                None
                if not unknown
                else "this code doesn't report analyzer_runs[...].parsed, "
                "so parse failures can't be counted"
            ),
        },
        "metrics": aggregate(
            [
                {
                    "diff": o.case.diff,
                    "expected": o.case.expected,
                    "findings": o.findings,
                    "raw_findings": o.raw_findings,
                    "error": o.error,
                }
                for o in outcomes
            ]
        ),
        "latency_ms": {
            "source": "measured" if mode == "live" else "recorded",
            "mean": round(statistics.mean(latencies)) if latencies else None,
            "p50": round(statistics.median(latencies)) if latencies else None,
            "max": max(latencies) if latencies else None,
            "note": LATENCY_NOTE,
        },
        "tokens": {
            "model_calls": len(all_calls),
            "prompt": sum(c["prompt_tokens"] for c in all_calls),
            "completion": sum(c["completion_tokens"] for c in all_calls),
        },
        "cost_usd": _cost(all_calls) if all_calls else None,
        "cases": per_case,
    }


# Keys of build_report() that describe one run; a multi-run report keeps them
# for every run under "runs".
RUN_KEYS = (
    "case_count",
    "cases_scored",
    "scored_case_ids",
    "errors",
    "anchoring",
    "parse_failures",
    "metrics",
    "latency_ms",
    "tokens",
    "cost_usd",
    "cases",
)
# (label, metrics key) for the variance table, in display order.
VARIANCE_METRICS = (
    ("Recall, exact line", "recall"),
    ("Recall, location-tolerant", "recall_tolerant"),
    ("Precision, exact location", "precision"),
    ("Precision, duplicates collapsed", "precision_dedup"),
    ("Precision, location-tolerant", "precision_tolerant"),
    ("False-positive rate on clean diffs", "clean_false_positive_rate"),
    ("Valid-line rate", "valid_line_rate"),
    ("Exact matches", "matched"),
    ("Near matches", "near"),
    ("Findings posted", "findings_total"),
    ("Findings on clean diffs", "clean_findings_total"),
    ("Cases scored", "cases_scored"),
)
COUNT_METRICS = {
    "matched",
    "near",
    "findings_total",
    "clean_findings_total",
    "cases_scored",
}
SCORE_KEYS = ("findings", "matched", "near", "partial", "missed", "extra")
FINDING_KEYS = ("file_path", "line_number", "category", "severity")


def spread(values: list[float | None]) -> dict[str, Any]:
    """Mean and min-max of the known values (None when none is known)."""
    known = [v for v in values if v is not None]
    return {
        "values": values,
        "mean": statistics.mean(known) if known else None,
        "min": min(known) if known else None,
        "max": max(known) if known else None,
    }


def case_scores_key(case: dict) -> tuple | None:
    """A case's score counts in one run; None if the case errored."""
    return None if case.get("error") else tuple(case[k] for k in SCORE_KEYS)


def case_findings_key(case: dict) -> tuple | None:
    """A case's posted findings by location, category and severity.

    The comment text is left out: it differs between almost any two runs.
    None if the case errored.
    """
    if case.get("error"):
        return None
    return tuple(
        sorted(
            json.dumps([f.get(k) for k in FINDING_KEYS])
            for f in case["posted_findings"]
        )
    )


def _largest_group(keys: list) -> int:
    known = [k for k in keys if k is not None]
    return max((known.count(k) for k in known), default=0)


def case_stability(runs: list[dict]) -> list[dict[str, Any]]:
    """Per case: how many runs agree on its scores and on its findings."""
    by_id: dict[str, list[dict]] = {}
    for report in runs:
        for case in report["cases"]:
            by_id.setdefault(case["id"], []).append(case)
    return [
        {
            "id": cid,
            "runs": len(cases),
            "runs_scored": sum(1 for c in cases if not c.get("error")),
            "agree_scores": _largest_group([case_scores_key(c) for c in cases]),
            "agree_findings": _largest_group([case_findings_key(c) for c in cases]),
            "findings": [None if c.get("error") else c["findings"] for c in cases],
            "matched": [None if c.get("error") else c["matched"] for c in cases],
        }
        for cid, cases in by_id.items()
    ]


def build_repeat_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine the reports of N runs of the same cases.

    One run: that run's report, unchanged. Several: the top-level fields are
    run 1's (so single-run tools still read the file), plus ``repeat``,
    ``runs`` (each run's own fields), ``variance`` (mean and min-max per
    metric) and ``case_stability``.
    """
    if len(reports) == 1:
        return reports[0]
    combined = dict(reports[0])
    combined["repeat"] = len(reports)
    combined["top_level_fields"] = (
        f"run 1 of {len(reports)}; see runs, variance and case_stability"
    )
    combined["runs"] = [{k: r[k] for k in RUN_KEYS} for r in reports]
    combined["variance"] = {
        key: spread(
            [
                r["cases_scored"] if key == "cases_scored" else r["metrics"].get(key)
                for r in reports
            ]
        )
        for _, key in VARIANCE_METRICS
    }
    combined["case_stability"] = case_stability(reports)
    combined["models_used"] = sorted({m for r in reports for m in r["models_used"]})
    combined["providers_used"] = sorted(
        {p for r in reports for p in r["providers_used"]}
    )
    return combined


def all_errors(report: dict[str, Any]) -> dict[str, str]:
    """Errors of every run, keyed ``case`` (one run) or ``run i: case``."""
    runs = report.get("runs")
    if not runs:
        return dict(report.get("errors") or {})
    return {
        f"run {i}: {cid}": err
        for i, r in enumerate(runs, 1)
        for cid, err in (r.get("errors") or {}).items()
    }


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _fmt_metric(value: float | None, key: str) -> str:
    if value is None:
        return "n/a"
    if key in COUNT_METRICS:
        return str(value) if isinstance(value, int) else f"{value:.1f}"
    return f"{value:.3f}"


def _fmt_values(values: list) -> str:
    return ", ".join("err" if v is None else str(v) for v in values)


def render_repeat_markdown(report: dict[str, Any]) -> str:
    """Markdown for a multi-run report: variance and per-case stability."""
    runs = report["runs"]
    scored = ", ".join(str(r["cases_scored"]) for r in runs)
    lines = [
        f"# Review eval results ({report['mode']}, {report['repeat']} runs)",
        "",
        f"**Scored per run: {scored} of {report['case_count']} cases.**"
        + (
            ""
            if all(r["cases_scored"] == r["case_count"] for r in runs)
            else " Errored cases count as missed (defects) or as false"
            " positives (clean diffs)."
        ),
        "",
        f"- Commit: `{report['commit']}`"
        + (
            " (uncommitted or untracked files present)"
            if report["dirty_worktree"]
            else ""
        ),
        f"- Date (UTC): {report['date_utc'] or 'n/a'} ({report['date_source']})",
        f"- Models used: {', '.join(report['models_used']) or 'none'}",
        f"- Run flags: {json.dumps(report['run_flags'], sort_keys=True)}",
        f"- Harness sha256: `{report['harness_sha256'][:16]}`, "
        f"case set sha256: `{report['case_set_sha256'][:16]}`",
        "",
        "Each metric across the runs: mean, min–max, and the value in each run.",
        "",
        "| Metric | Mean | Min–max | Per run |",
        "| --- | --- | --- | --- |",
    ]
    for label, key in VARIANCE_METRICS:
        s = report["variance"][key]
        per_run = ", ".join(_fmt_metric(v, key) for v in s["values"])
        lines.append(
            f"| {label} | {_fmt_metric(s['mean'], key)} | "
            f"{_fmt_metric(s['min'], key)}–{_fmt_metric(s['max'], key)} | "
            f"{per_run} |"
        )
    lines += [
        "",
        "Per-case stability: how many of the runs that scored the case agree on "
        "its scores (findings, matched, near, partial, missed, extra) and on its "
        "posted findings (file, line, category and severity; the comment text "
        "is not compared). `err` marks a run where the case errored.",
        "",
        "| Case | Runs scored | Same scores | Same findings | Findings per run "
        "| Matched per run |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in report["case_stability"]:
        lines.append(
            f"| {c['id']} | {c['runs_scored']}/{c['runs']} | "
            f"{c['agree_scores']}/{c['runs_scored']} | "
            f"{c['agree_findings']}/{c['runs_scored']} | "
            f"{_fmt_values(c['findings'])} | {_fmt_values(c['matched'])} |"
        )
    errors = all_errors(report)
    if errors:
        lines += ["", "Errors:"]
        lines += [f"- {k}: {v}" for k, v in errors.items()]
    return "\n".join(lines) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    if report.get("runs"):
        return render_repeat_markdown(report)
    m = report["metrics"]
    lat = report["latency_ms"]
    tok = report["tokens"]
    cost = report["cost_usd"]
    pf = report["parse_failures"]
    anch = report["anchoring"]
    scored, total = report["cases_scored"], report["case_count"]
    lines = [
        f"# Review eval results ({report['mode']})",
        "",
        f"**Scored {scored} of {total} cases.**"
        + (
            ""
            if scored == total
            else " Errored cases count as missed (defects) or as false"
            " positives (clean diffs); see the Error column."
        ),
        "",
        f"- Commit: `{report['commit']}`"
        + (
            " (uncommitted or untracked files present)"
            if report["dirty_worktree"]
            else ""
        ),
        f"- Date (UTC): {report['date_utc'] or 'n/a'} ({report['date_source']})",
        f"- Models used: {', '.join(report['models_used']) or 'none'}",
        f"- Run flags: {json.dumps(report['run_flags'], sort_keys=True)}",
        f"- Post-processing: {', '.join(report['post_processing']) or 'none'}",
        f"- Harness sha256: `{report['harness_sha256'][:16]}`, "
        f"case set sha256: `{report['case_set_sha256'][:16]}`",
        f"- Cases: {total} ({m['clean_cases']} clean)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Precision (exact location) | {_fmt(m['precision'])} "
        f"({m['matched']}/{m['findings_total']} findings) |",
        f"| Precision, duplicates collapsed | {_fmt(m['precision_dedup'])} "
        f"({m['matched_dedup']}/{m['unique_findings_total']} unique findings) |",
        f"| Precision (location-tolerant) | {_fmt(m['precision_tolerant'])} "
        f"({m['matched'] + m['near']}/{m['findings_total']} findings) |",
        f"| Recall (exact line) | {_fmt(m['recall'])} "
        f"({m['matched']}/{m['expected_total']} expected) |",
        f"| Recall (location-tolerant) | {_fmt(m['recall_tolerant'])} "
        f"({m['matched'] + m['near']}/{m['expected_total']} expected) |",
        f"| False-positive rate on clean diffs | "
        f"{_fmt(m['clean_false_positive_rate'])} "
        f"({m['clean_cases_with_findings'] + m['clean_cases_errored']}"
        f"/{m['clean_cases']} cases) |",
        f"| Valid-line rate (agent output, before anchoring) | "
        f"{_fmt(m['valid_line_rate'])} "
        f"({m['valid_line_findings']}/{m['raw_findings_total']} findings) |",
        f"| Near / partial matches | {m['near']} / {m['partial']} |",
        "| Analyzer parse failures | "
        + (
            str(pf["analyzer_runs_failed"])
            if pf["analyzer_runs_failed"] is not None
            else f"unknown ({pf['note']})"
        )
        + " |",
        "| Anchoring (anchored / snapped / file-level) | "
        + (
            f"{anch['anchored']} / {anch['snapped']} / {anch['unanchored']}"
            if anch
            else "not applied"
        )
        + " |",
        f"| Latency per case, ms ({lat['source']}; providers: "
        f"{', '.join(report['providers_used']) or 'none'}) | mean {lat['mean']}, "
        f"p50 {lat['p50']}, max {lat['max']} |",
        f"| Model calls / prompt tokens / completion tokens | "
        f"{tok['model_calls']} / {tok['prompt']} / {tok['completion']} |",
        f"| Cost (USD) | {'not priced' if cost is None else cost} |",
        "",
        f"{lat['note']} Precision is measured against the labels: a real issue "
        "nobody labeled, or a duplicate, counts as an extra. Exact recall needs "
        "the exact labeled line range; location-tolerant recall also accepts "
        "the same file within 3 lines or in the same hunk.",
        "",
        "| Case | Expected | Findings | Matched | Near | Partial | Missed | Extra "
        "| Error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in report["cases"]:
        lines.append(
            f"| {c['id']} | {c['expected']} | {c['findings']} | {c['matched']} "
            f"| {c['near']} | {c['partial']} | {c['missed']} | {c['extra']} | "
            f"{c['error'] or ''} |"
        )
    return "\n".join(lines) + "\n"


def write_results(
    report: dict[str, Any], results_dir: Path, name: str | None = None
) -> tuple[Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = name or (
        report["commit"][:12] if report["commit"] != "unknown" else "unknown"
    )
    json_path = results_dir / f"{stem}.json"
    md_path = results_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    md_path.write_text(render_markdown(report))
    return json_path, md_path


@contextmanager
def restrict_provider(provider: str | None) -> Iterator[None]:
    """Limit the server provider chain to one provider for this run.

    Free-tier quotas can run out partway through a run; pinning one provider
    keeps a recording from silently mixing models. With None, nothing changes.
    """
    if provider is None:
        yield
        return
    from services import llm_client as llm_module

    chain = [c for c in llm_module.MODEL_CHAIN if c.provider.value == provider]
    if not chain:
        configured = sorted({c.provider.value for c in llm_module.MODEL_CHAIN})
        raise ValueError(
            f"provider {provider!r} is not configured; configured: {configured}"
        )
    with patch.object(llm_module, "MODEL_CHAIN", chain):
        yield


def temperature_settings() -> dict[str, Any]:
    """
    The temperature settings a live run's requests used, for its results.

    The cassettes don't record them, so two live runs at different settings
    can only be told apart by this.
    """
    from core.config import get_settings

    s = get_settings()
    return {
        "review": s.review_temperature,
        "google": s.google_temperature,
        "groq": s.groq_temperature,
    }


async def run(
    mode: str,
    cases: list[Case],
    cassettes_dir: Path,
    record: bool = False,
    pause: float = 0.0,
    provider: str | None = None,
    run_index: int | None = None,
) -> list[CaseOutcome]:
    """Run the cases one at a time, waiting ``pause`` seconds between them.

    ``run_index`` selects the numbered cassettes (``<case>.<i>.json``) to
    replay or record; None uses ``<case>.json``.
    """
    outcomes = []
    with restrict_provider(provider):
        for i, case in enumerate(cases):  # sequential: predictable rate limits
            if i and pause > 0:
                await asyncio.sleep(pause)
            if mode == "replay":
                outcomes.append(await replay_case(case, cassettes_dir, run_index))
            else:
                outcomes.append(
                    await live_case(case, cassettes_dir if record else None, run_index)
                )
    return outcomes


async def run_repeated(
    mode: str,
    cases: list[Case],
    cassettes_dir: Path,
    run_indexes: list[int | None],
    record: bool = False,
    pause: float = 0.0,
    provider: str | None = None,
) -> list[list[CaseOutcome]]:
    """One full pass over the cases per run index, pausing between passes."""
    runs = []
    for n, run_index in enumerate(run_indexes):
        if n and pause > 0:
            await asyncio.sleep(pause)
        runs.append(
            await run(
                mode,
                cases,
                cassettes_dir,
                record,
                pause=pause,
                provider=provider,
                run_index=run_index,
            )
        )
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay", action="store_true", help="use cassettes")
    mode.add_argument("--live", action="store_true", help="call real providers")
    parser.add_argument("--record", action="store_true", help="live: save cassettes")
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--cassettes-dir", type=Path, default=CASSETTES_DIR)
    parser.add_argument(
        "--results-dir", type=Path, help="write <name>.json and <name>.md here"
    )
    parser.add_argument(
        "--results-name", help="file name stem for results (default: commit sha)"
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="write results even if some cases errored",
    )
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument(
        "--no-feedback",
        action="store_true",
        help="run feedback cases without their examples "
        "(cassettes <case>.no-feedback.json)",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="wait this long between cases (free-tier rate limits)",
    )
    parser.add_argument(
        "--provider",
        metavar="NAME",
        help="live: use only this server provider, e.g. groq or google",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="live: run every case N times (records <case>.<i>.json when N > 1)",
    )
    args = parser.parse_args(argv)

    if args.record and not args.live:
        parser.error("--record needs --live")
    if args.provider and not args.live:
        parser.error("--provider needs --live")
    if args.pause < 0:
        parser.error("--pause must be >= 0")
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    if args.repeat > 1 and not args.live:
        parser.error("--repeat needs --live (replay replays every recorded run)")
    if args.replay:
        # Never read the developer's .env in replay; no provider is called.
        os.environ["DEVMIND_ENV_FILE"] = ""

    only = set(args.only.split(",")) if args.only else None
    cases = load_cases(args.cases_dir, only)
    if args.no_feedback:
        cases = [case.without_feedback() for case in cases]
    if args.replay and not any(args.cassettes_dir.glob("*.json")):
        print(
            f"No cassettes in {args.cassettes_dir}. Record them for this code "
            "with `make eval-record` (provider keys needed). The pre-fix "
            "baseline cassettes are on branch eval/baseline-prefix and only "
            "replay against that branch's prompts.",
            file=sys.stderr,
        )
        return 2

    commit, dirty = git_state()
    mode_name = "live" if args.live else "replay"
    date = _now_utc() if args.live else None
    flags = {
        "pause": args.pause,
        "provider": args.provider,
        "only": sorted(only) if only else None,
        "record": args.record,
        "allow_partial": args.allow_partial,
        "feedback": not args.no_feedback,
    }
    if args.live:
        run_indexes = [None] if args.repeat == 1 else list(range(1, args.repeat + 1))
    else:
        run_indexes = recorded_runs(args.cassettes_dir) or [None]
    if len(run_indexes) > 1:
        flags["repeat"] = len(run_indexes)
    if args.live:
        flags["temperatures"] = temperature_settings()
    try:
        runs = asyncio.run(
            run_repeated(
                mode_name,
                cases,
                args.cassettes_dir,
                run_indexes,
                args.record,
                pause=args.pause,
                provider=args.provider,
            )
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    report = build_repeat_report(
        [build_report(o, mode_name, commit, dirty, date, flags) for o in runs]
    )
    print(render_markdown(report))
    errors = all_errors(report)
    if errors and not report.get("runs"):
        print(
            f"Scored {report['cases_scored']} of {report['case_count']} cases; "
            f"errored: {', '.join(errors)}",
            file=sys.stderr,
        )
    elif errors:
        print(f"Errored (run: case): {', '.join(errors)}", file=sys.stderr)
    if args.results_dir:
        if errors and not args.allow_partial:
            print(
                "Not writing results: some cases errored. Fix or re-record "
                "them, or pass --allow-partial to write a partial result.",
                file=sys.stderr,
            )
            return 1
        json_path, md_path = write_results(report, args.results_dir, args.results_name)
        print(f"Wrote {json_path} and {md_path}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
