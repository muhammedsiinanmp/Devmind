"""
Anchor review comments to lines that exist in the PR diff.

GitHub rejects an inline comment whose line is not an added or context line
of the diff. A comment on such a line is kept inline, moved to the nearest
diff line within SNAP_DISTANCE lines of the same hunk, or turned into a
file-level note (line_number 0), which the poster folds into the review body.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from models.review import ReviewComment
from services.code_parser import DiffChunk

logger = logging.getLogger(__name__)

SNAP_DISTANCE = 3


@dataclass
class AnchorStats:
    """How many comments were kept, moved or turned into file-level notes."""

    anchored: int = 0
    snapped: int = 0
    unanchored: int = 0


def build_line_index(chunks: list[DiffChunk]) -> dict[str, list[list[int]]]:
    """Map each file path to the commentable new-file lines of each hunk."""
    index: dict[str, list[list[int]]] = {}
    for chunk in chunks:
        for hunk in chunk.hunks:
            lines = [
                ln.new_line
                for ln in hunk.lines
                if ln.kind in ("added", "context") and ln.new_line is not None
            ]
            if lines:
                index.setdefault(chunk.file_path, []).append(lines)
    return index


def _nearest_line(hunks: list[list[int]], line: int) -> Optional[int]:
    """Nearest commentable line within SNAP_DISTANCE; ties go to the lower line."""
    best: Optional[int] = None
    for hunk_lines in hunks:
        for candidate in hunk_lines:
            distance = abs(candidate - line)
            if distance > SNAP_DISTANCE:
                continue
            if best is None or (distance, candidate) < (abs(best - line), best):
                best = candidate
    return best


def anchor_comments(
    chunks: list[DiffChunk], comments: list[ReviewComment]
) -> tuple[list[ReviewComment], AnchorStats]:
    """
    Keep every comment, with its line_number set to a line in the diff or 0.

    Args:
        chunks: Parsed diff chunks (from parse_diff)
        comments: Review comments from the agent

    Returns:
        (anchored comments in the original order, counts)
    """
    index = build_line_index(chunks)
    stats = AnchorStats()
    result: list[ReviewComment] = []

    for comment in comments:
        hunks = index.get(comment.file_path, [])
        line = comment.line_number
        if line > 0 and any(line in hunk_lines for hunk_lines in hunks):
            stats.anchored += 1
            result.append(comment)
            continue

        nearest = _nearest_line(hunks, line) if line > 0 else None
        if nearest is not None:
            stats.snapped += 1
            result.append(comment.model_copy(update={"line_number": nearest}))
        else:
            stats.unanchored += 1
            result.append(comment.model_copy(update={"line_number": 0}))

    logger.info(
        "review.anchoring anchored=%d snapped=%d unanchored=%d",
        stats.anchored,
        stats.snapped,
        stats.unanchored,
    )
    return result, stats
