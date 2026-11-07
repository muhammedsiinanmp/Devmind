"""
Feedback examples (issue #74): DevMind comments that developers accepted or
rejected, stored in feedback_embeddings and shown to later reviews of the
same repository as "Previously accepted findings" and "Previously rejected
findings".

Django decides what counts as accepted or rejected (docs/feedback-learning.md)
and sends each comment's verdict to POST /feedback/upsert. The comment's code
hunk is embedded in the same form as a review's retrieval queries (the
router's _chunk_text), so a review reuses its code-search query embeddings to
find the feedback whose code looks most like the new diff.
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.embeddings import FeedbackEmbedding
from services.code_parser import parse_diff

logger = logging.getLogger(__name__)

# Examples of each signal given to one review, and the cosine similarity a
# stored hunk needs to one of the review's hunks. The threshold is a guess,
# not tuned on data: it is higher than code search's 0.6 because a rejected
# example that only loosely matches could hide a real finding.
FEEDBACK_TOP_K = 3
FEEDBACK_THRESHOLD = 0.7
# Rows read per query embedding before the threshold and top-k are applied.
FEEDBACK_CANDIDATES = 10

# Limits on what one example puts in the prompt.
MAX_BODY_CHARS = 600
MAX_CODE_LINES = 30
MAX_CODE_CHARS = 1500
# Limits on what is stored.
MAX_STORED_CHARS = 4000


@dataclass(frozen=True)
class FeedbackExample:
    """One accepted or rejected comment, as shown in a review prompt."""

    file_path: str
    category: str
    severity: str
    body: str
    code: str = ""
    similarity: Optional[float] = None


@dataclass
class FeedbackContext:
    """Formatted examples for the prompt's two feedback sections."""

    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.accepted or self.rejected)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " [cut]"


def _clip_code(code: str) -> str:
    lines = code.strip("\n").splitlines()
    clipped = "\n".join(lines[:MAX_CODE_LINES])
    if len(lines) > MAX_CODE_LINES:
        clipped += f"\n[{len(lines) - MAX_CODE_LINES} more lines cut]"
    if len(clipped) > MAX_CODE_CHARS:
        clipped = clipped[:MAX_CODE_CHARS] + " [cut]"
    return clipped


def format_feedback_example(example: FeedbackExample) -> str:
    """
    One example as prompt text: where it was, the comment, then its code.

    The prompt builder escapes and wraps it as untrusted data.
    """
    details = [example.category, example.severity]
    if example.similarity is not None:
        details.append(f"similarity {example.similarity:.2f}")
    lines = [
        f"{example.file_path} ({', '.join(d for d in details if d)})",
        f"Comment: {_clip(example.body, MAX_BODY_CHARS)}",
    ]
    if example.code.strip():
        lines.append("Code:")
        lines.append(_clip_code(example.code))
    return "\n".join(lines)


def feedback_context(
    accepted: list[FeedbackExample], rejected: list[FeedbackExample]
) -> FeedbackContext:
    return FeedbackContext(
        accepted=[format_feedback_example(e) for e in accepted],
        rejected=[format_feedback_example(e) for e in rejected],
    )


def document_text(
    file_path: str, code_hunk: str, body: str, chunk_text: Callable
) -> str:
    """
    The text embedded for a stored example.

    The hunk is parsed and rendered with ``chunk_text`` (the router's
    _chunk_text), the form a review's queries use, so similarities between
    them are meaningful. Without a hunk, the comment body is embedded.
    """
    if code_hunk.strip():
        path = file_path or "file"
        diff = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n{code_hunk}"
        chunks = parse_diff(diff)
        text = "\n".join(t for t in map(chunk_text, chunks) if t)
        if text:
            return text[:MAX_STORED_CHARS]
        return code_hunk[:MAX_STORED_CHARS]
    return body[:MAX_STORED_CHARS]


async def delete_feedback(session: AsyncSession, comment_id: int) -> int:
    """Delete a comment's stored examples (every model). Returns the count."""
    result = await session.execute(
        delete(FeedbackEmbedding).where(FeedbackEmbedding.comment_id == comment_id)
    )
    await session.commit()
    return result.rowcount or 0


async def replace_feedback(
    session: AsyncSession,
    *,
    comment_id: int,
    repo_full_name: str,
    signal: str,
    file_path: str,
    category: str,
    severity: str,
    body: str,
    code_hunk: str,
    embedding: list[float],
    embedding_model: str,
    source_ref: Optional[str] = None,
) -> None:
    """
    Store a comment's example for ``embedding_model``, replacing an older one.
    ``source_ref`` ("PR#<n>") is the PR the comment was on.
    """
    await session.execute(
        delete(FeedbackEmbedding).where(
            FeedbackEmbedding.comment_id == comment_id,
            FeedbackEmbedding.embedding_model == embedding_model,
        )
    )
    session.add(
        FeedbackEmbedding(
            repo_full_name=repo_full_name,
            comment_id=comment_id,
            signal=signal,
            file_path=file_path[:500],
            category=category[:20],
            severity=severity[:20],
            body=body[:MAX_STORED_CHARS],
            code_hunk=code_hunk[:MAX_STORED_CHARS],
            embedding=embedding,
            embedding_model=embedding_model,
            source_ref=source_ref,
        )
    )
    await session.commit()


def select_examples(
    rows: list[tuple[FeedbackEmbedding, float]],
    top_k: int = FEEDBACK_TOP_K,
    threshold: float = FEEDBACK_THRESHOLD,
) -> tuple[list[FeedbackExample], list[FeedbackExample]]:
    """
    The best ``top_k`` accepted and rejected examples among ``rows``.

    ``rows`` are (row, similarity) pairs from every query; a row found by
    several queries keeps its best similarity. Rows under ``threshold`` are
    dropped.
    """
    best: dict[int, tuple[FeedbackEmbedding, float]] = {}
    for row, similarity in rows:
        if similarity < threshold:
            continue
        kept = best.get(row.comment_id)
        if kept is None or similarity > kept[1]:
            best[row.comment_id] = (row, similarity)

    ranked = sorted(best.values(), key=lambda pair: -pair[1])
    by_signal: dict[str, list[FeedbackExample]] = {"accepted": [], "rejected": []}
    for row, similarity in ranked:
        examples = by_signal.get(row.signal)
        if examples is None or len(examples) >= top_k:
            continue
        examples.append(
            FeedbackExample(
                file_path=row.file_path,
                category=row.category,
                severity=row.severity,
                body=row.body,
                code=row.code_hunk,
                similarity=round(similarity, 4),
            )
        )
    return by_signal["accepted"], by_signal["rejected"]


async def search_feedback(
    session: AsyncSession,
    query_embeddings: list[list[float]],
    repo_full_name: str,
    embedding_model: str,
    top_k: int = FEEDBACK_TOP_K,
    threshold: float = FEEDBACK_THRESHOLD,
    exclude_source_ref: Optional[str] = None,
) -> FeedbackContext:
    """
    The repository's accepted and rejected examples closest to the review's
    hunks, formatted for the prompt. Only rows of ``embedding_model`` are
    read, and rows with ``exclude_source_ref`` (the PR under review) are
    left out, so a PR's own feedback never steers its later reviews.
    """
    rows: list[tuple[FeedbackEmbedding, float]] = []
    for query_embedding in query_embeddings:
        distance = FeedbackEmbedding.embedding.cosine_distance(query_embedding).label(
            "distance"
        )
        stmt = select(FeedbackEmbedding, distance).where(
            FeedbackEmbedding.repo_full_name == repo_full_name,
            FeedbackEmbedding.embedding_model == embedding_model,
        )
        if exclude_source_ref is not None:
            stmt = stmt.where(
                FeedbackEmbedding.source_ref.is_distinct_from(exclude_source_ref)
            )
        result = await session.execute(
            stmt.order_by(distance).limit(FEEDBACK_CANDIDATES)
        )
        rows.extend((row, 1.0 - float(dist)) for row, dist in result.all())
    accepted, rejected = select_examples(rows, top_k, threshold)
    logger.info(
        "feedback.search repo=%s accepted=%d rejected=%d",
        repo_full_name,
        len(accepted),
        len(rejected),
    )
    return feedback_context(accepted, rejected)
