"""
LangGraph Review Agent.

Three analyzers (security, quality, tests) run in parallel, one LLM call each,
then synthesize deduplicates and ranks their findings. An analyzer repeats its
call once only when the model's response can't be parsed.

A diff too big for one prompt is split into batches of whole files
(services/diff_batching.py); the graph runs once per batch and
run_review_agent merges the batches' findings.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.states import AnalyzerRun, ReviewState, ReviewComment
from core.config import get_settings
from models.review import ReviewFinding, ReviewFindings, Severity
from services.code_parser import parse_diff
from services.diff_batching import SKIP_DEADLINE, ReviewDeadlineError, plan_batches
from services.llm_client import llm_client
from services.prompt_builder import (
    PromptContext,
    build_review_prompt,
    diff_token_budget,
    REVIEW_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# Extra attempts an analyzer gets when its response can't be parsed.
MAX_PARSE_RETRIES = 1
# The reply that means "no issues", from the output schema.
EMPTY_REPLY = json.dumps(ReviewFindings().model_dump())
# Sent after an unparseable reply, before the single retry.
CORRECTIVE_PROMPT = (
    "Your previous reply was not the JSON object described in the output format. "
    f"Reply with only that JSON object, or {EMPTY_REPLY} if there are no issues."
)
# Fixed order used to pick model_used, so it doesn't depend on branch timing.
ANALYZER_ORDER = ("security", "quality", "tests")
# Rank of each schema severity, most severe first.
SEVERITY_ORDER = {severity.value: rank for rank, severity in enumerate(Severity)}


def create_system_message(category: str) -> str:
    """Create category-specific system message."""
    messages = {
        "security": f"{REVIEW_SYSTEM_PROMPT}\n\nFocus on security vulnerabilities like SQL injection, XSS, command injection, hardcoded secrets, and authentication issues.",
        "quality": f"{REVIEW_SYSTEM_PROMPT}\n\nFocus on code quality: readability, performance, error handling, and best practices.",
        "tests": f"{REVIEW_SYSTEM_PROMPT}\n\nFocus on test coverage, test patterns, and missing test cases.",
    }
    return messages.get(category, REVIEW_SYSTEM_PROMPT)


async def _run_analyzer(
    state: ReviewState,
    category: str,
    context: PromptContext,
    instruction: str,
) -> tuple[list[ReviewComment], AnalyzerRun]:
    """
    Call the LLM for one analyzer and parse its findings.

    If the response can't be parsed, the model's reply and CORRECTIVE_PROMPT
    are appended and the call is repeated, up to MAX_PARSE_RETRIES times. A
    parsed empty list is a valid result and is never retried. Latency and
    token counts are summed over attempts; token counts stay None if the
    provider never reports them. run["parsed"] is False if every attempt
    failed to parse.
    """
    prompt = state.get("prebuilt_prompt") or build_review_prompt(context)
    messages = [
        {"role": "system", "content": create_system_message(category)},
        {
            "role": "user",
            "content": f"{prompt}\n\n{instruction} Reply with only the JSON object described in the output format. If there are no issues, reply with {EMPTY_REPLY}",
        },
    ]
    settings = get_settings()

    run: AnalyzerRun = {
        "model": "",
        "latency_ms": 0,
        "prompt_tokens": None,
        "completion_tokens": None,
        "attempts": 0,
        "parsed": False,
    }
    comments: list[ReviewComment] | None = None
    previous_reply: str | None = None

    while comments is None and run["attempts"] <= MAX_PARSE_RETRIES:
        if previous_reply is not None:
            # Some OpenAI-compatible endpoints reject an empty assistant
            # message, so an empty reply is left out of the retry.
            if previous_reply:
                messages = messages + [{"role": "assistant", "content": previous_reply}]
            messages = messages + [{"role": "user", "content": CORRECTIVE_PROMPT}]
        run["attempts"] += 1
        started = time.perf_counter()
        response = await llm_client.generate(
            messages,
            user_id=state.get("user_id"),
            temperature=settings.review_temperature,
            json_mode=True,
        )
        run["latency_ms"] += int((time.perf_counter() - started) * 1000)
        run["model"] = response.model_used
        for key in ("prompt_tokens", "completion_tokens"):
            value = getattr(response, key)
            if value is not None:
                run[key] = (run[key] or 0) + value
        comments = _parse_llm_comment_list(response.content, category)
        previous_reply = response.content or ""

    run["parsed"] = comments is not None

    logger.info(
        "analyze_%s found=%d attempts=%d",
        category,
        len(comments or []),
        run["attempts"],
    )
    return comments or [], run


async def analyze_security(state: ReviewState) -> dict[str, Any]:
    """Analyze the diff for security vulnerabilities (one LLM call)."""
    logger.info("analyze_security repo=%s", state["repo_full_name"])

    context = PromptContext(
        diff_chunks=state.get("diff_chunks") or parse_diff(state["diff_text"]),
        similar_patterns=state.get("similar_patterns", []),
    )
    comments, run = await _run_analyzer(
        state, "security", context, "Analyze for security vulnerabilities."
    )
    return {"security_comments": comments, "analyzer_runs": {"security": run}}


async def analyze_quality(state: ReviewState) -> dict[str, Any]:
    """Analyze the diff for code quality issues (one LLM call)."""
    logger.info("analyze_quality repo=%s", state["repo_full_name"])

    context = PromptContext(
        diff_chunks=state.get("diff_chunks") or parse_diff(state["diff_text"]),
    )
    comments, run = await _run_analyzer(
        state, "quality", context, "Analyze for quality issues."
    )
    return {"quality_comments": comments, "analyzer_runs": {"quality": run}}


async def analyze_tests(state: ReviewState) -> dict[str, Any]:
    """Analyze the diff for missing tests (one LLM call)."""
    logger.info("analyze_tests repo=%s", state["repo_full_name"])

    context = PromptContext(
        diff_chunks=state.get("diff_chunks") or parse_diff(state["diff_text"]),
    )
    comments, run = await _run_analyzer(
        state, "tests", context, "Analyze test coverage."
    )
    return {"test_comments": comments, "analyzer_runs": {"tests": run}}


# "findings" is the schema's key; the others are tolerated from models that
# ignore the output format.
_LIST_KEYS = (*ReviewFindings.model_fields, "issues", "comments", "results", "data")


def _parse_llm_comments(content: str, default_category: str) -> list[ReviewComment]:
    """Parse LLM response into ReviewComment list ([] if unparseable)."""
    return _parse_llm_comment_list(content, default_category) or []


def _parse_llm_comment_list(
    content: str, default_category: str
) -> list[ReviewComment] | None:
    """Parse LLM response into ReviewComment list, or None if unparseable.

    The expected reply is the ReviewFindings object, {"findings": [...]}.
    As a fallback for providers without JSON mode, it also handles:
    - Bare JSON array:              [...]
    - Markdown-fenced JSON:         ```json\\n[...]\\n```
    - Other wrapper keys:           {"issues": [...]}
    - One finding, no wrapper:      {"file_path": ..., "body": "...", ...}
    - Prefix text before array:     "Here are the issues: [...]"

    "{}" and a known key set to null ({"issues": null}) mean no findings.
    Each item is validated against ReviewFinding; invalid items are skipped.
    """
    if not content:
        logger.warning("llm_parse_failed category=%s empty response", default_category)
        return None

    # Strip markdown code fences before attempting any parse
    cleaned = re.sub(r"```(?:json)?\s*", "", content).strip()

    raw_list: list | None = None

    # Strategy 1: direct json.loads — handles bare array and dict-wrapped
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            raw_list = parsed
        elif isinstance(parsed, dict):
            if not parsed:
                raw_list = []
            for key in _LIST_KEYS:
                if key in parsed and (
                    parsed[key] is None or isinstance(parsed[key], list)
                ):
                    raw_list = parsed[key] or []
                    break
            if raw_list is None and isinstance(parsed.get("body"), str):
                # One finding without the wrapper, as some models send
                # in JSON mode.
                raw_list = [parsed]
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract outermost [...] then parse — handles prefix text
    if raw_list is None:
        start = cleaned.find("[")
        end = cleaned.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                parsed = json.loads(cleaned[start:end])
                if isinstance(parsed, list):
                    raw_list = parsed
            except json.JSONDecodeError:
                pass

    if raw_list is None:
        # The reply can quote diff code, so only its length and hash are logged.
        logger.warning(
            "llm_parse_failed category=%s length=%d sha256=%s",
            default_category,
            len(content),
            hashlib.sha256(content.encode()).hexdigest()[:12],
        )
        return None

    comments: list[ReviewComment] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        try:
            v = ReviewFinding.model_validate(
                {
                    "file_path": item.get("file_path", ""),
                    "line_number": item.get("line_number", 0),
                    "category": item.get("category", default_category),
                    "severity": item.get("severity", "warning"),
                    "body": item.get("body", ""),
                    "suggested_fix": item.get("suggested_fix"),
                }
            )
            comments.append(
                {
                    "file_path": v.file_path,
                    "line_number": v.line_number,
                    "category": v.category,
                    "severity": v.severity.value,
                    "body": v.body,
                    "suggested_fix": v.suggested_fix,
                }
            )
        except Exception:
            continue

    return comments


async def synthesize(state: ReviewState) -> dict[str, Any]:
    """
    Merge findings from all analyzers.

    Deduplicates, ranks by severity and sets model_used from analyzer_runs.
    """
    logger.info("synthesize")

    unique_comments = _dedupe_and_rank(
        state.get("security_comments", [])
        + state.get("quality_comments", [])
        + state.get("test_comments", [])
    )

    logger.info("synthesize unique=%d", len(unique_comments))

    runs = state.get("analyzer_runs", {})
    model_used = next(
        (
            runs[name]["model"]
            for name in ANALYZER_ORDER
            if runs.get(name, {}).get("model")
        ),
        "",
    )

    return {
        "synthesized_comments": unique_comments,
        "model_used": model_used,
    }


def _dedupe_and_rank(comments: list[ReviewComment]) -> list[ReviewComment]:
    """Keep the first comment per (file, line, category), most severe first."""
    seen = set()
    unique_comments = []

    for comment in comments:
        key = (
            comment.get("file_path", ""),
            comment.get("line_number", 0),
            comment.get("category", ""),
        )
        if key not in seen:
            seen.add(key)
            unique_comments.append(comment)

    unique_comments.sort(key=lambda c: SEVERITY_ORDER.get(c.get("severity", "info"), 4))
    return unique_comments


def build_review_graph():
    """
    Build the Review Agent state graph.

    Returns compiled StateGraph.
    """
    graph = StateGraph(ReviewState)

    graph.add_node("analyze_security", analyze_security)
    graph.add_node("analyze_quality", analyze_quality)
    graph.add_node("analyze_tests", analyze_tests)
    graph.add_node("synthesize", synthesize)

    for analyzer in ("analyze_security", "analyze_quality", "analyze_tests"):
        graph.add_edge(START, analyzer)
        graph.add_edge(analyzer, "synthesize")

    graph.add_edge("synthesize", END)

    return graph.compile()


review_graph = build_review_graph()


def _merge_runs(runs: list[AnalyzerRun]) -> AnalyzerRun:
    """One analyzer's runs over all batches: counts summed, parsed if all were."""
    merged: AnalyzerRun = {
        "model": next((r["model"] for r in runs if r.get("model")), ""),
        "latency_ms": sum(r.get("latency_ms", 0) for r in runs),
        "prompt_tokens": None,
        "completion_tokens": None,
        "attempts": sum(r.get("attempts", 0) for r in runs),
        "parsed": all(r.get("parsed", False) for r in runs),
    }
    for key in ("prompt_tokens", "completion_tokens"):
        values = [r[key] for r in runs if r.get(key) is not None]
        if values:
            merged[key] = sum(values)
    return merged


def _merge_batch_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Combine the final states of several batches into one result.

    Comments are deduplicated and ranked again over all batches, analyzer_runs
    are summed per analyzer and model_used is the first batch's.
    """
    if len(results) == 1:
        return dict(results[0])
    merged: dict[str, Any] = {
        key: [c for result in results for c in result.get(key, [])]
        for key in ("security_comments", "quality_comments", "test_comments")
    }
    merged["synthesized_comments"] = _dedupe_and_rank(
        [c for result in results for c in result.get("synthesized_comments", [])]
    )
    names = [n for n in ANALYZER_ORDER if any(n in r["analyzer_runs"] for r in results)]
    merged["analyzer_runs"] = {
        name: _merge_runs(
            [r["analyzer_runs"][name] for r in results if name in r["analyzer_runs"]]
        )
        for name in names
    }
    merged["model_used"] = next(
        (r["model_used"] for r in results if r.get("model_used")), ""
    )
    return merged


async def run_review_agent(
    diff_text: str,
    repo_full_name: str,
    pr_number: int = 0,
    user_id: int = 0,
    diff_chunks: list | None = None,
    similar_patterns: list[str] | None = None,
    share_prompt: bool = False,
    deadline_seconds: float | None = None,
) -> dict[str, Any]:
    """
    Run the full review agent.

    The diff's files are planned into batches (services/diff_batching.py):
    generated and vendored files are skipped, and the rest are packed into
    batches that each fit one prompt. The analyzer graph runs once per batch,
    at most review_max_concurrent_batches at a time, and the results are
    merged. A diff that fits in one batch is reviewed exactly as before.

    Batches still running when the deadline passes are cancelled; the
    findings of finished batches are returned and the unfinished batches'
    files are reported as skipped with reason "deadline". If no batch
    finished (or the deadline had passed before any started),
    ReviewDeadlineError is raised instead. If a batch fails, the other
    batches are cancelled and its exception is raised.

    Args:
        diff_text: Git diff text
        repo_full_name: Repository full name (owner/repo)
        pr_number: PR number
        user_id: User ID
        diff_chunks: Pre-parsed diff chunks (parsed from diff_text if empty)
        similar_patterns: Retrieved similar code for the security prompt
        share_prompt: Give all three analyzers the security prompt (the
            batch's diff plus similar_patterns), as the router does
        deadline_seconds: Time the batches may take (default:
            review_deadline_seconds)

    Returns:
        Final state, including synthesized_comments, analyzer_runs,
        model_used, files_reviewed and files_skipped
        (``[{"file_path", "reason"}]``)
    """
    settings = get_settings()
    chunks = diff_chunks or parse_diff(diff_text)
    patterns = similar_patterns or []
    plan = plan_batches(
        chunks,
        diff_token_budget(PromptContext(diff_chunks=chunks, similar_patterns=patterns)),
        settings.review_skip_patterns,
        settings.review_max_batches,
    )
    if len(plan.batches) > 1 or plan.files_skipped:
        logger.info(
            "review.batches repo=%s pr=%s batches=%d reviewed=%d skipped=%d",
            repo_full_name,
            pr_number,
            len(plan.batches),
            len(plan.files_reviewed),
            len(plan.files_skipped),
        )

    if deadline_seconds is None:
        deadline_seconds = settings.review_deadline_seconds
    semaphore = asyncio.Semaphore(settings.review_max_concurrent_batches)
    # Set when a batch fails or the deadline passes, so a batch that was
    # waiting for a slot doesn't start its LLM calls before it is cancelled.
    stopped = False

    async def review_batch(batch: list) -> dict[str, Any] | None:
        nonlocal stopped
        prompt = ""
        if share_prompt:
            prompt = build_review_prompt(
                PromptContext(diff_chunks=batch, similar_patterns=patterns)
            )
        initial_state: ReviewState = {
            "diff_text": diff_text,
            "repo_full_name": repo_full_name,
            "pr_number": pr_number,
            "user_id": user_id,
            "diff_chunks": batch,
            "similar_patterns": patterns,
            "prebuilt_prompt": prompt,
            "security_comments": [],
            "quality_comments": [],
            "test_comments": [],
            "synthesized_comments": [],
            "analyzer_runs": {},
            "model_used": "",
        }
        async with semaphore:
            if stopped:
                return None
            try:
                return await review_graph.ainvoke(initial_state)
            except BaseException:
                stopped = True
                raise

    if plan.batches and deadline_seconds <= 0:
        # Don't start calls (or take rate-limit tokens) for a review that's over.
        raise ReviewDeadlineError(
            f"review deadline passed before any of {len(plan.batches)} batches started"
        )
    tasks = [asyncio.create_task(review_batch(batch)) for batch in plan.batches]
    pending: set[asyncio.Task] = set()
    try:
        if tasks:
            _, pending = await asyncio.wait(
                tasks,
                timeout=max(deadline_seconds, 0),
                return_when=asyncio.FIRST_EXCEPTION,
            )
    finally:
        # Also runs if this coroutine is cancelled, so no batch outlives it.
        unfinished = [task for task in tasks if not task.done()]
        if unfinished:
            stopped = True
            for task in unfinished:
                task.cancel()
            await asyncio.gather(*unfinished, return_exceptions=True)

    failed = [
        task
        for task in tasks
        if task not in pending and not task.cancelled() and task.exception()
    ]
    if failed:
        # Its own exception, so callers can still catch it by type.
        raise failed[0].exception()

    finished = [
        (batch, task.result())
        for batch, task in zip(plan.batches, tasks)
        if task not in pending and task.result() is not None
    ]
    timed_out = [batch for batch, task in zip(plan.batches, tasks) if task in pending]
    if timed_out:
        logger.warning(
            "review.deadline repo=%s pr=%s deadline_s=%s finished=%d unfinished=%d",
            repo_full_name,
            pr_number,
            deadline_seconds,
            len(finished),
            len(timed_out),
        )
    if timed_out and not finished:
        # An empty result would look like a clean review of an unreviewed diff.
        raise ReviewDeadlineError(
            f"review deadline ({deadline_seconds:.0f}s) passed before any of "
            f"{len(timed_out)} batches finished"
        )

    if finished:
        result = _merge_batch_results([batch_result for _, batch_result in finished])
    else:
        result = {
            "security_comments": [],
            "quality_comments": [],
            "test_comments": [],
            "synthesized_comments": [],
            "analyzer_runs": {},
            "model_used": "",
        }
    result["files_reviewed"] = [c.file_path for batch, _ in finished for c in batch]
    result["files_skipped"] = [asdict(skipped) for skipped in plan.files_skipped] + [
        {"file_path": c.file_path, "reason": SKIP_DEADLINE}
        for batch in timed_out
        for c in batch
    ]
    return result
