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


def reduce_model_used(current: str, new_value: str) -> str:
    """Keep the most recent non-empty model string."""
    return new_value or current


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

    # ── intermediate ─────────────────────────────────────────────────────────
    conventions: dict

    # ── FIX: Annotated with _extend_list so parallel branches accumulate ─────
    # Without this, last-write-wins and two of the three analyzers are silently
    # discarded.
    security_comments: Annotated[list[ReviewComment], _extend_list]
    quality_comments: Annotated[list[ReviewComment], _extend_list]
    test_comments: Annotated[list[ReviewComment], _extend_list]

    # ── outputs ──────────────────────────────────────────────────────────────
    synthesized_comments: list[ReviewComment]
    suggested_fixes: list[dict]

    model_used: Annotated[str, reduce_model_used]
    confidence: float
    iteration: int


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
