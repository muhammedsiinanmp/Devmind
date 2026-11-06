"""
Pydantic models for review API.
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    """Severity of a finding, most severe first."""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# Fallback for models that answer with the common high/medium/low scale.
SEVERITY_ALIASES = {"high": "error", "medium": "warning", "low": "info"}


class ReviewFinding(BaseModel):
    """
    One finding as the LLM must return it.

    This model is the single source of truth for the review output: the
    prompt's output-format text is generated from it (output_format_text) and
    every reply is validated against it.
    """

    file_path: str = Field(
        default="", description="path of the file, as shown after 'File:'"
    )
    line_number: int = Field(
        default=0,
        description="the <n> of the added or context line the finding is about",
    )
    category: str = Field(
        default="general", description="short label, such as security or quality"
    )
    severity: Severity = Field(
        default=Severity.WARNING, description="how serious the finding is"
    )
    body: str = Field(default="", description="what is wrong and why")
    suggested_fix: str | None = Field(
        default=None, description="replacement code, or null if there is none"
    )

    @field_validator("severity", mode="before")
    @classmethod
    def normalise_severity(cls, v: object) -> str:
        """Lowercase, map high/medium/low, and turn unknown values into warning."""
        s = str(getattr(v, "value", v)).strip().lower()
        s = SEVERITY_ALIASES.get(s, s)
        return s if s in {m.value for m in Severity} else Severity.WARNING.value


class ReviewFindings(BaseModel):
    """The whole LLM reply: a JSON object holding the list of findings."""

    findings: list[ReviewFinding] = Field(default_factory=list)


def _type_text(annotation: object) -> str:
    if annotation is Severity:
        return "one of: " + ", ".join(s.value for s in Severity)
    if annotation is int:
        return "integer"
    if annotation is str:
        return "string"
    if annotation == str | None:
        return "string or null"
    raise TypeError(f"no prompt text for field type {annotation!r}")


def output_format_text() -> str:
    """The output-format instructions for the prompt, generated from the schema."""
    (key,) = ReviewFindings.model_fields
    fields = "\n".join(
        f"  - {name} ({_type_text(field.annotation)}): {field.description}"
        for name, field in ReviewFinding.model_fields.items()
    )
    return (
        "Output format:\n"
        f'- Reply with only a JSON object, no prose: {{"{key}": [<finding>, ...]}}\n'
        f'- If there are no issues, reply with: {{"{key}": []}}\n'
        "- Each finding is an object with these fields:\n"
        f"{fields}"
    )


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
    parsed: bool = Field(
        description="False if every attempt returned an unparseable reply",
    )


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
    anchored: int = Field(default=0, description="Comments already on a diff line")
    snapped: int = Field(default=0, description="Comments moved to a nearby diff line")
    unanchored: int = Field(
        default=0, description="Comments turned into file-level notes (line 0)"
    )


class ReviewError(BaseModel):
    """Error response."""

    error: str
    message: str
