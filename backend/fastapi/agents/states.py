"""
State definitions for LangGraph agents.

Contains ReviewState and BugIntelState TypedDicts.
"""

from typing import TypedDict, Optional


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

    diff_text: str
    repo_full_name: str
    pr_number: int
    user_id: int

    conventions: dict
    security_comments: list[ReviewComment]
    quality_comments: list[ReviewComment]
    test_comments: list[ReviewComment]

    synthesized_comments: list[ReviewComment]
    suggested_fixes: list[dict]

    model_used: str
    confidence: float

    iteration: int


class BugIntelComment(TypedDict):
    """A comment from bug intelligence."""

    bug_type: str
    severity: str
    description: str
    affected_files: list[str]
    suggested_fix: str


class BugIntelState(TypedDict):
    """State for the Bug Intelligence Agent."""

    issue_description: str
    repo_full_name: str

    similar_bugs: list[BugIntelComment]
    root_cause: str
    fix_suggestion: str

    model_used: str
    confidence: float
