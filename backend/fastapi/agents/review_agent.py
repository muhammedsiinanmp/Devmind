"""
LangGraph Review Agent with 7 nodes.

Implements the full review workflow for analyzing code changes.
"""

import json
import logging
import re
from typing import Any

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, field_validator

from agents.states import ReviewState, ReviewComment
from services.code_parser import DiffChunk, parse_diff
from services.llm_client import llm_client
from services.prompt_builder import (
    PromptContext,
    build_review_prompt,
    REVIEW_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.7
MAX_ITERATIONS = 3
SEVERITY_ORDER = {"critical": 0, "error": 1, "warning": 2, "info": 3}


def create_system_message(category: str) -> str:
    """Create category-specific system message."""
    messages = {
        "security": f"{REVIEW_SYSTEM_PROMPT}\n\nFocus on security vulnerabilities like SQL injection, XSS, command injection, hardcoded secrets, and authentication issues.",
        "quality": f"{REVIEW_SYSTEM_PROMPT}\n\nFocus on code quality: readability, performance, error handling, and best practices.",
        "tests": f"{REVIEW_SYSTEM_PROMPT}\n\nFocus on test coverage, test patterns, and missing test cases.",
    }
    return messages.get(category, REVIEW_SYSTEM_PROMPT)


async def fetch_conventions(state: ReviewState) -> dict[str, Any]:
    """
    Node 1: Fetch repository conventions from database.

    For now, returns empty dict (Phase 3 will populate from MongoDB).
    """
    logger.info("fetch_conventions repo=%s", state["repo_full_name"])

    conventions = {}

    return {
        "conventions": conventions,
    }


async def analyze_security(state: ReviewState) -> dict[str, Any]:
    """
    Node 2: Analyze code for security vulnerabilities.

    Calls LLM to identify security issues.
    """
    logger.info("analyze_security repo=%s", state["repo_full_name"])

    diff_chunks = state.get("diff_chunks") or parse_diff(state["diff_text"])
    context = PromptContext(
        diff_chunks=diff_chunks,
        similar_patterns=state.get("similar_patterns", [])
        or state.get("conventions", {}).get("security_patterns", []),
    )

    prompt = state.get("prebuilt_prompt") or build_review_prompt(context)
    system_msg = create_system_message("security")

    messages = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": f"{prompt}\n\nAnalyze for security vulnerabilities. Return JSON list with: file_path, line_number, category, severity, body, suggested_fix.",
        },
    ]

    response = await llm_client.generate(messages, user_id=state.get("user_id"))

    comments = _parse_llm_comments(response.content, "security")

    logger.info("analyze_security found=%d", len(comments))

    return {
        "security_comments": comments,
        "model_used": response.model_used,
    }


async def analyze_quality(state: ReviewState) -> dict[str, Any]:
    """
    Node 3: Analyze code for quality issues.

    Calls LLM to identify code quality problems.
    """
    logger.info("analyze_quality repo=%s", state["repo_full_name"])

    diff_chunks = state.get("diff_chunks") or parse_diff(state["diff_text"])
    context = PromptContext(
        diff_chunks=diff_chunks,
        quality_patterns=state.get("conventions", {}).get("quality_patterns", []),
    )

    prompt = state.get("prebuilt_prompt") or build_review_prompt(context)
    system_msg = create_system_message("quality")

    messages = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": f"{prompt}\n\nAnalyze for quality issues. Return JSON list with: file_path, line_number, category, severity, body, suggested_fix.",
        },
    ]

    response = await llm_client.generate(messages, user_id=state.get("user_id"))

    comments = _parse_llm_comments(response.content, "quality")

    logger.info("analyze_quality found=%d", len(comments))

    return {
        "quality_comments": comments,
        "model_used": response.model_used,
    }


async def analyze_tests(state: ReviewState) -> dict[str, Any]:
    """
    Node 4: Analyze code for test coverage.

    Calls LLM to identify missing tests.
    """
    logger.info("analyze_tests repo=%s", state["repo_full_name"])

    diff_chunks = state.get("diff_chunks") or parse_diff(state["diff_text"])
    context = PromptContext(
        diff_chunks=diff_chunks,
    )

    prompt = state.get("prebuilt_prompt") or build_review_prompt(context)
    system_msg = create_system_message("tests")

    messages = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": f"{prompt}\n\nAnalyze test coverage. Return JSON list with: file_path, line_number, category, severity, body, suggested_fix.",
        },
    ]

    response = await llm_client.generate(messages, user_id=state.get("user_id"))

    comments = _parse_llm_comments(response.content, "tests")

    logger.info("analyze_tests found=%d", len(comments))

    return {
        "test_comments": comments,
        "model_used": response.model_used,
    }


_SEVERITY_VALUES = {"critical", "error", "warning", "info"}


class _LLMCommentSchema(BaseModel):
    file_path: str = ""
    line_number: int = 0
    category: str = "general"
    severity: str = "warning"
    body: str = ""
    suggested_fix: str | None = None

    @field_validator("severity", mode="before")
    @classmethod
    def normalise_severity(cls, v: object) -> str:
        s = str(v).lower()
        return s if s in _SEVERITY_VALUES else "warning"


def _parse_llm_comments(content: str, default_category: str) -> list[ReviewComment]:
    """Parse LLM response into ReviewComment list.

    Handles four real-world LLM output formats:
    - Bare JSON array:              [...]
    - Markdown-fenced JSON:         ```json\\n[...]\\n```
    - Dict-wrapped array:           {"issues": [...]}
    - Prefix text before array:     "Here are the issues: [...]"
    """
    if not content:
        return []

    # Strip markdown code fences before attempting any parse
    cleaned = re.sub(r"```(?:json)?\s*", "", content).strip()

    raw_list: list | None = None

    # Strategy 1: direct json.loads — handles bare array and dict-wrapped
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            raw_list = parsed
        elif isinstance(parsed, dict):
            for key in ("issues", "comments", "findings", "results", "data"):
                if isinstance(parsed.get(key), list):
                    raw_list = parsed[key]
                    break
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
        logger.warning(
            "llm_parse_failed category=%s preview=%.200s",
            default_category,
            content,
        )
        return []

    comments: list[ReviewComment] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        try:
            v = _LLMCommentSchema.model_validate(
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
                    "severity": v.severity,
                    "body": v.body,
                    "suggested_fix": v.suggested_fix,
                }
            )
        except Exception:
            continue

    return comments


async def synthesize(state: ReviewState) -> dict[str, Any]:
    """
    Node 5: Synthesize comments from all analyzers.

    Deduplicates and ranks by severity.
    """
    logger.info("synthesize")

    all_comments = (
        state.get("security_comments", [])
        + state.get("quality_comments", [])
        + state.get("test_comments", [])
    )

    seen = set()
    unique_comments = []

    for comment in all_comments:
        key = (
            comment.get("file_path", ""),
            comment.get("line_number", 0),
            comment.get("category", ""),
        )
        if key not in seen:
            seen.add(key)
            unique_comments.append(comment)

    unique_comments.sort(key=lambda c: SEVERITY_ORDER.get(c.get("severity", "info"), 4))

    logger.info("synthesize unique=%d", len(unique_comments))

    return {
        "synthesized_comments": unique_comments,
    }


async def generate_fixes(state: ReviewState) -> dict[str, Any]:
    """
    Node 6: Generate suggested fixes.

    Only generates fixes for critical/error severity.
    """
    logger.info("generate_fixes")

    fixes = []

    for comment in state.get("synthesized_comments", []):
        severity = comment.get("severity", "")
        if severity in ("critical", "error"):
            fix = comment.get("suggested_fix", "")
            if fix:
                fixes.append(
                    {
                        "file_path": comment.get("file_path", ""),
                        "line_number": comment.get("line_number", 0),
                        "fix": fix,
                    }
                )

    logger.info("generate_fixes count=%d", len(fixes))

    return {
        "suggested_fixes": fixes,
    }


async def format_output(state: ReviewState) -> dict[str, Any]:
    """
    Node 7: Format final output.

    Computes confidence based on findings relative to diff size.
    Small diffs (≤10 lines) always pass. Larger diffs need at least
    1 comment per 50 diff lines to reach the confidence threshold.
    """
    comments = state.get("synthesized_comments", [])
    total = len(comments)
    diff_lines = len(state.get("diff_text", "").splitlines())

    if diff_lines <= 10:
        # Trivial diff — zero findings is acceptable
        confidence = 1.0
    elif total == 0:
        # Non-trivial diff with no findings — suspicious, trigger retry
        confidence = 0.0
    else:
        expected_min = max(1, diff_lines // 50)
        confidence = min(1.0, total / expected_min)

    iteration = state.get("iteration", 0)

    logger.info(
        "format_output confidence=%.2f iteration=%d comments=%d diff_lines=%d",
        confidence,
        iteration,
        total,
        diff_lines,
    )

    return {
        "confidence": confidence,
        "iteration": iteration + 1,
    }


def should_retry(state: ReviewState) -> bool:
    """Determine if retry is needed."""
    confidence = state.get("confidence", 1.0)
    iteration = state.get("iteration", 0)

    return confidence < CONFIDENCE_THRESHOLD and iteration < MAX_ITERATIONS


def build_review_graph():
    """
    Build the Review Agent state graph.

    Returns compiled StateGraph.
    """
    graph = StateGraph(ReviewState)

    graph.add_node("fetch_conventions", fetch_conventions)
    graph.add_node("analyze_security", analyze_security)
    graph.add_node("analyze_quality", analyze_quality)
    graph.add_node("analyze_tests", analyze_tests)
    graph.add_node("synthesize", synthesize)
    graph.add_node("generate_fixes", generate_fixes)
    graph.add_node("format_output", format_output)

    graph.set_entry_point("fetch_conventions")

    graph.add_edge("fetch_conventions", "analyze_security")
    graph.add_edge("fetch_conventions", "analyze_quality")
    graph.add_edge("fetch_conventions", "analyze_tests")

    graph.add_edge("analyze_security", "synthesize")
    graph.add_edge("analyze_quality", "synthesize")
    graph.add_edge("analyze_tests", "synthesize")

    graph.add_edge("synthesize", "generate_fixes")
    graph.add_edge("generate_fixes", "format_output")

    def retry_condition(state: ReviewState) -> str:
        if should_retry(state):
            # Return to fetch_conventions so all three analysis nodes re-run,
            # making new LLM calls. _extend_list reducers accumulate findings;
            # synthesize deduplicates them across iterations.
            return "fetch_conventions"
        return END

    graph.add_conditional_edges(
        "format_output",
        retry_condition,
    )

    return graph.compile()


review_graph = build_review_graph()


async def run_review_agent(
    diff_text: str,
    repo_full_name: str,
    pr_number: int = 0,
    user_id: int = 0,
    diff_chunks: list | None = None,
    similar_patterns: list[str] | None = None,
    prebuilt_prompt: str = "",
) -> dict[str, Any]:
    """
    Run the full review agent.

    Args:
        diff_text: Git diff text
        repo_full_name: Repository full name (owner/repo)
        pr_number: PR number
        user_id: User ID

    Returns:
        Final state with review results
    """
    initial_state: ReviewState = {
        "diff_text": diff_text,
        "repo_full_name": repo_full_name,
        "pr_number": pr_number,
        "user_id": user_id,
        "diff_chunks": diff_chunks or [],
        "similar_patterns": similar_patterns or [],
        "prebuilt_prompt": prebuilt_prompt,
        "conventions": {},
        "security_comments": [],
        "quality_comments": [],
        "test_comments": [],
        "synthesized_comments": [],
        "suggested_fixes": [],
        "model_used": "",
        "confidence": 0.0,
        "iteration": 0,
    }

    result = await review_graph.ainvoke(initial_state)
    return result
