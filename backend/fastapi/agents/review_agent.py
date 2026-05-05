"""
LangGraph Review Agent with 7 nodes.

Implements the full review workflow for analyzing code changes.
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph

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

    diff_chunks = parse_diff(state["diff_text"])
    context = PromptContext(
        diff_chunks=diff_chunks,
        similar_patterns=state.get("conventions", {}).get("security_patterns", []),
    )

    prompt = build_review_prompt(context)
    system_msg = create_system_message("security")

    messages = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": f"{prompt}\n\nAnalyze for security vulnerabilities. Return JSON list with: file_path, line_number, category, severity, body, suggested_fix.",
        },
    ]

    response = await llm_client.generate(messages)

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

    diff_chunks = parse_diff(state["diff_text"])
    context = PromptContext(
        diff_chunks=diff_chunks,
        quality_patterns=state.get("conventions", {}).get("quality_patterns", []),
    )

    prompt = build_review_prompt(context)
    system_msg = create_system_message("quality")

    messages = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": f"{prompt}\n\nAnalyze for quality issues. Return JSON list with: file_path, line_number, category, severity, body, suggested_fix.",
        },
    ]

    response = await llm_client.generate(messages)

    comments = _parse_llm_comments(response.content, "quality")

    logger.info("analyze_quality found=%d", len(comments))

    return {
        "quality_comments": comments,
    }


async def analyze_tests(state: ReviewState) -> dict[str, Any]:
    """
    Node 4: Analyze code for test coverage.

    Calls LLM to identify missing tests.
    """
    logger.info("analyze_tests repo=%s", state["repo_full_name"])

    diff_chunks = parse_diff(state["diff_text"])
    context = PromptContext(
        diff_chunks=diff_chunks,
    )

    prompt = build_review_prompt(context)
    system_msg = create_system_message("tests")

    messages = [
        {"role": "system", "content": system_msg},
        {
            "role": "user",
            "content": f"{prompt}\n\nAnalyze test coverage. Return JSON list with: file_path, line_number, category, severity, body, suggested_fix.",
        },
    ]

    response = await llm_client.generate(messages)

    comments = _parse_llm_comments(response.content, "tests")

    logger.info("analyze_tests found=%d", len(comments))

    return {
        "test_comments": comments,
    }


def _parse_llm_comments(content: str, default_category: str) -> list[ReviewComment]:
    """Parse LLM response into ReviewComment list."""
    import json

    comments = []

    try:
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            data = json.loads(content[start:end])
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        comments.append(
                            {
                                "file_path": item.get("file_path", ""),
                                "line_number": item.get("line_number", 0),
                                "category": item.get("category", default_category),
                                "severity": item.get("severity", "warning"),
                                "body": item.get("body", ""),
                                "suggested_fix": item.get("suggested_fix"),
                            }
                        )
    except (json.JSONDecodeError, ValueError):
        pass

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

    Computes confidence and prepares response.
    """
    logger.info("format_output")

    comments = state.get("synthesized_comments", [])
    total = len(comments)

    if total == 0:
        confidence = 1.0
    else:
        failed = sum(1 for c in comments if not c.get("body"))
        confidence = 1.0 - (failed / total)

    iteration = state.get("iteration", 0)

    logger.info(
        "format_output confidence=%.2f iteration=%d",
        confidence,
        iteration,
    )

    return {
        "confidence": confidence,
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
            return "synthesize"
        return END

    graph.add_conditional_edges(
        "format_output",
        retry_condition,
    )

    graph.add_edge("format_output", END)

    return graph.compile()


review_graph = build_review_graph()


async def run_review_agent(
    diff_text: str,
    repo_full_name: str,
    pr_number: int = 0,
    user_id: int = 0,
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

    iteration = result.get("iteration", 0)
    if (
        result.get("confidence", 1.0) < CONFIDENCE_THRESHOLD
        and iteration < MAX_ITERATIONS
    ):
        for i in range(iteration, MAX_ITERATIONS):
            result["iteration"] = i + 1

            result = await review_graph.ainvoke(result)

            if result.get("confidence", 1.0) >= CONFIDENCE_THRESHOLD:
                break

    return result
