from typing import TypedDict, Optional, Annotated


def _extend_list(current: list, new_value: list) -> list:
    """
    Reducer that extends a list rather than replacing it.
    Used on comment fields so parallel analyzer nodes accumulate results.
    """
    if not isinstance(current, list):
        current = []
    if not isinstance(new_value, list):
        return current
    return current + new_value


def _merge_dict(current: dict, new_value: dict) -> dict:
    """
    Reducer that merges dicts. Used on analyzer_runs, which all three parallel
    analyzer nodes write in the same step, each under its own key.
    """
    if not isinstance(current, dict):
        current = {}
    if not isinstance(new_value, dict):
        return current
    return {**current, **new_value}


class AnalyzerRun(TypedDict, total=False):
    """Telemetry for one analyzer node (summed over its attempts)."""

    model: str
    latency_ms: int
    prompt_tokens: Optional[int]  # None if the provider never reported it
    completion_tokens: Optional[int]
    attempts: int
    parsed: bool  # False if every attempt returned an unparseable reply


class ReviewComment(TypedDict):
    """A single review comment."""

    file_path: str
    line_number: int
    category: str
    severity: str
    body: str
    suggested_fix: Optional[str]


class ReviewState(TypedDict):
    """State for the Review Agent graph."""

    # ── inputs ───────────────────────────────────────────────────────────────
    diff_text: str
    repo_full_name: str
    pr_number: int
    user_id: int
    diff_chunks: list
    similar_patterns: list
    prebuilt_prompt: str

    # ── FIX: Annotated with _extend_list so parallel branches accumulate ─────
    # Without this, last-write-wins and two of the three analyzers are silently
    # discarded.
    security_comments: Annotated[list[ReviewComment], _extend_list]
    quality_comments: Annotated[list[ReviewComment], _extend_list]
    test_comments: Annotated[list[ReviewComment], _extend_list]

    # ── outputs ──────────────────────────────────────────────────────────────
    synthesized_comments: list[ReviewComment]

    # One entry per analyzer ("security", "quality", "tests").
    analyzer_runs: Annotated[dict[str, AnalyzerRun], _merge_dict]
    # Set once by synthesize from analyzer_runs, so it does not depend on
    # which parallel branch finished last.
    model_used: str


class BugIntelComment(TypedDict):
    bug_type: str
    severity: str
    description: str
    affected_files: list[str]
    suggested_fix: str


class BugIntelState(TypedDict):
    issue_description: str
    repo_full_name: str
    similar_bugs: list[BugIntelComment]
    root_cause: str
    fix_suggestion: str
    model_used: str
    confidence: float
