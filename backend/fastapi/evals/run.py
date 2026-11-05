"""
Run the review agent over the labeled eval cases and score it.

    uv run python -m evals.run --replay              # offline, from cassettes
    uv run python -m evals.run --live --record \\
        --results-dir evals/results                  # real providers

Runs ``run_review_agent`` directly, without the router's database/RAG step,
so no Postgres is needed. Only ``llm_client.generate`` is swapped out: in
replay it serves recorded responses, in live mode it is wrapped so the
responses can be recorded.
"""

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from evals.cases import CASES_DIR, Case, load_cases
from evals.cassette import (
    CassetteMiss,
    Player,
    Recorder,
    load_cassette,
    save_cassette,
)
from evals.matcher import aggregate, is_valid_line, match_case, new_side_lines

EVALS_DIR = Path(__file__).parent
CASSETTES_DIR = EVALS_DIR / "cassettes"
RESULTS_DIR = EVALS_DIR / "results"
REPO_NAME = "devmind-evals/synthetic"

# USD per million tokens, keyed by the client's model_used string
# (e.g. "groq/llama-3.3-70b-versatile"). Empty on purpose: add a price only
# from the provider's published pricing. Unpriced runs report cost as null.
PRICES_PER_MTOK: dict[str, dict[str, float]] = {}


@dataclass
class CaseOutcome:
    case: Case
    findings: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def git_state() -> tuple[str, bool]:
    sha = _git("rev-parse", "HEAD") or "unknown"
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return sha, dirty


def _visible_findings(result: dict) -> list[dict]:
    # Same filter as routers/review.py: comments without a body are dropped.
    return [
        dict(c)
        for c in result.get("synthesized_comments", []) or []
        if isinstance(c, dict) and c.get("body")
    ]


def _replay_response(call: dict):
    from services.llm_client import LLMProvider, LLMResponse

    prefix = call["model_used"].split("/", 1)[0]
    try:
        provider = LLMProvider(prefix)
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
    from services.llm_client import llm_client

    with patch.object(llm_client, "generate", generate):
        return await run_review_agent(diff_text=case.diff, repo_full_name=REPO_NAME)


async def replay_case(case: Case, cassettes_dir: Path) -> CaseOutcome:
    outcome = CaseOutcome(case=case)
    try:
        cassette = load_cassette(
            cassettes_dir / f"{case.id}.json", case.id, case.digest
        )
        player = Player(cassette["calls"], _replay_response)
        result = await _run_agent(case, player)
        outcome.findings = _visible_findings(result)
        outcome.calls = player.calls
        outcome.latency_ms = cassette["latency_ms"]
    except (CassetteMiss, ValueError) as exc:
        outcome.error = f"{type(exc).__name__}: {exc}"
    return outcome


async def live_case(case: Case, cassettes_dir: Path | None) -> CaseOutcome:
    from core.config import get_settings
    from services.llm_client import llm_client

    s = get_settings()
    secrets = [
        s.google_ai_api_key,
        s.groq_api_key,
        s.github_token,
        s.fastapi_internal_secret,
    ]
    recorder = Recorder(llm_client.generate, secrets=secrets)
    outcome = CaseOutcome(case=case)
    start = time.perf_counter()
    try:
        result = await _run_agent(case, recorder)
    except Exception as exc:  # keep going; the case is reported as an error
        outcome.error = f"{type(exc).__name__}: {exc}"
        return outcome
    outcome.latency_ms = int((time.perf_counter() - start) * 1000)
    outcome.findings = _visible_findings(result)
    outcome.calls = recorder.calls
    if cassettes_dir is not None:
        save_cassette(
            cassettes_dir / f"{case.id}.json",
            case.id,
            case.digest,
            recorder.calls,
            outcome.latency_ms,
        )
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


def build_report(
    outcomes: list[CaseOutcome],
    mode: str,
    commit: str,
    dirty: bool,
    date: str | None,
) -> dict[str, Any]:
    scored = [o for o in outcomes if o.error is None]
    all_calls = [c for o in scored for c in o.calls]
    latencies = [o.latency_ms for o in scored]
    per_case = []
    for o in outcomes:
        res = match_case(o.case.expected, o.findings)
        lines = new_side_lines(o.case.diff)
        per_case.append(
            {
                "id": o.case.id,
                "clean": not o.case.expected,
                "error": o.error,
                "expected": len(o.case.expected),
                "findings": len(o.findings),
                "matched": len(res.matched),
                "partial": len(res.partial),
                "missed": len(res.missed),
                "extra": len(res.extra),
                "valid_lines": sum(is_valid_line(f, lines) for f in o.findings),
                "latency_ms": o.latency_ms,
                "model_calls": len(o.calls),
                "raw_findings": [
                    {
                        k: f.get(k)
                        for k in (
                            "file_path",
                            "line_number",
                            "category",
                            "severity",
                            "body",
                        )
                    }
                    for f in o.findings
                ],
            }
        )
    return {
        "mode": mode,
        "commit": commit,
        "dirty_worktree": dirty,
        "date_utc": date,
        "models_used": sorted({c["model_used"] for c in all_calls}),
        "case_count": len(outcomes),
        "cases_scored": len(scored),
        "errors": {o.case.id: o.error for o in outcomes if o.error},
        "metrics": aggregate(
            [
                {
                    "diff": o.case.diff,
                    "expected": o.case.expected,
                    "findings": o.findings,
                }
                for o in scored
            ]
        ),
        "latency_ms": {
            "source": "measured" if mode == "live" else "recorded",
            "mean": round(statistics.mean(latencies)) if latencies else None,
            "p50": round(statistics.median(latencies)) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "tokens": {
            "model_calls": len(all_calls),
            "prompt": sum(c["prompt_tokens"] for c in all_calls),
            "completion": sum(c["completion_tokens"] for c in all_calls),
        },
        "cost_usd": _cost(all_calls) if all_calls else None,
        "cases": per_case,
    }


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_markdown(report: dict[str, Any]) -> str:
    m = report["metrics"]
    lat = report["latency_ms"]
    tok = report["tokens"]
    cost = report["cost_usd"]
    lines = [
        f"# Review eval results ({report['mode']})",
        "",
        f"- Commit: `{report['commit']}`"
        + (" (uncommitted changes present)" if report["dirty_worktree"] else ""),
        f"- Date (UTC): {report['date_utc'] or 'n/a (replay)'}",
        f"- Models used: {', '.join(report['models_used']) or 'none'}",
        f"- Cases: {report['case_count']} "
        f"({m['clean_cases']} clean scored), scored {report['cases_scored']}",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Precision | {_fmt(m['precision'])} "
        f"({m['matched']}/{m['findings_total']} findings) |",
        f"| Recall | {_fmt(m['recall'])} "
        f"({m['matched']}/{m['expected_total']} expected) |",
        f"| False-positive rate on clean diffs | "
        f"{_fmt(m['clean_false_positive_rate'])} "
        f"({m['clean_cases_with_findings']}/{m['clean_cases']} cases) |",
        f"| Valid-line rate | {_fmt(m['valid_line_rate'])} "
        f"({m['valid_line_findings']}/{m['findings_total']} findings) |",
        f"| Partial matches | {m['partial']} |",
        f"| Latency per case, ms ({lat['source']}) | mean {lat['mean']}, "
        f"p50 {lat['p50']}, max {lat['max']} |",
        f"| Model calls / prompt tokens / completion tokens | "
        f"{tok['model_calls']} / {tok['prompt']} / {tok['completion']} |",
        f"| Cost (USD) | {'not priced' if cost is None else cost} |",
        "",
        "| Case | Expected | Findings | Matched | Partial | Missed | Extra | Error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in report["cases"]:
        lines.append(
            f"| {c['id']} | {c['expected']} | {c['findings']} | {c['matched']} "
            f"| {c['partial']} | {c['missed']} | {c['extra']} | "
            f"{c['error'] or ''} |"
        )
    return "\n".join(lines) + "\n"


def write_results(report: dict[str, Any], results_dir: Path) -> tuple[Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = report["commit"][:12] if report["commit"] != "unknown" else "unknown"
    json_path = results_dir / f"{stem}.json"
    md_path = results_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    md_path.write_text(render_markdown(report))
    return json_path, md_path


async def run(
    mode: str,
    cases: list[Case],
    cassettes_dir: Path,
    record: bool = False,
) -> list[CaseOutcome]:
    outcomes = []
    for case in cases:  # sequential: keeps provider rate limits predictable
        if mode == "replay":
            outcomes.append(await replay_case(case, cassettes_dir))
        else:
            outcomes.append(await live_case(case, cassettes_dir if record else None))
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay", action="store_true", help="use cassettes")
    mode.add_argument("--live", action="store_true", help="call real providers")
    parser.add_argument("--record", action="store_true", help="live: save cassettes")
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--cassettes-dir", type=Path, default=CASSETTES_DIR)
    parser.add_argument(
        "--results-dir", type=Path, help="write <sha>.json and <sha>.md here"
    )
    parser.add_argument("--only", help="comma-separated case ids")
    args = parser.parse_args(argv)

    if args.record and not args.live:
        parser.error("--record needs --live")
    if args.replay:
        # Never read the developer's .env in replay; no provider is called.
        os.environ["DEVMIND_ENV_FILE"] = ""

    only = set(args.only.split(",")) if args.only else None
    cases = load_cases(args.cases_dir, only)
    if args.replay and not any(args.cassettes_dir.glob("*.json")):
        print(
            f"No cassettes in {args.cassettes_dir}. The baseline has not been "
            "recorded yet: run `make eval-record` with provider keys set.",
            file=sys.stderr,
        )
        return 2

    commit, dirty = git_state()
    mode_name = "live" if args.live else "replay"
    date = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if args.live else None
    )
    outcomes = asyncio.run(run(mode_name, cases, args.cassettes_dir, args.record))
    report = build_report(outcomes, mode_name, commit, dirty, date)
    print(render_markdown(report))
    if args.results_dir:
        json_path, md_path = write_results(report, args.results_dir)
        print(f"Wrote {json_path} and {md_path}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
