"""
Pydantic models for review API.
"""

from pydantic import BaseModel, Field


class ReviewComment(BaseModel):
    """A single review comment."""

    file_path: str
    line_number: int
    category: str
    severity: str
    body: str
    suggested_fix: str | None = None


class ReviewRequest(BaseModel):
    """Request to analyze a PR diff."""

    diff: str = Field(..., description="Git diff text")
    repo_full_name: str = Field(..., description="Repository full name (owner/repo)")
    pr_number: int = Field(default=0, description="PR number")
    user_id: int = Field(default=0, description="Owning user ID for BYOK priority")


class AnalyzerRun(BaseModel):
    """Telemetry for one review analyzer, summed over its attempts."""

    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: int = 1


class ReviewResponse(BaseModel):
    """Response from review analysis."""

    repo_full_name: str
    pr_number: int
    comments: list[ReviewComment] = Field(default_factory=list)
    risk_score: int = Field(ge=0, le=100, description="Risk score 0-100")
    model_used: str
    provider: str
    latency_ms: int
    analyzer_runs: dict[str, AnalyzerRun] = Field(
        default_factory=dict,
        description="Per-analyzer model, latency and token counts",
    )


class ReviewError(BaseModel):
    """Error response."""

    error: str
    message: str
