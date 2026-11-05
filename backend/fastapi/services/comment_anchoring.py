"""
Anchor review comments to lines that exist in the PR diff.

GitHub rejects an inline comment whose line is not an added or context line
of the diff. A comment on such a line is kept inline. One within
SNAP_DISTANCE lines of exactly one hunk is moved to that hunk's nearest
line. Any other comment becomes a file-level note (line_number 0), which the
poster folds into the review body.
"""

import logging
import re
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
    """
    Nearest commentable line of the one hunk within SNAP_DISTANCE.

    Returns None when no hunk is in reach, or when more than one is, because
    then it is unclear which hunk the comment is about. Ties inside the hunk
    go to the lower line.
    """
    in_reach = [
        hunk_lines
        for hunk_lines in hunks
        if any(abs(candidate - line) <= SNAP_DISTANCE for candidate in hunk_lines)
    ]
    if len(in_reach) != 1:
        return None
    return min(in_reach[0], key=lambda candidate: (abs(candidate - line), candidate))


def _snap(comment: ReviewComment, line: int) -> ReviewComment:
    """
    Move a comment to ``line``.

    A suggested fix was written for the original line, and GitHub would offer
    it as a one-click replacement of the new line, so it moves into the body
    as plain text instead.
    """
    update: dict = {"line_number": line}
    if comment.suggested_fix:
        fix = comment.suggested_fix
        # The fence must be longer than any backtick run inside the fix.
        longest_run = max((len(run) for run in re.findall(r"`+", fix)), default=0)
        fence = "`" * max(3, longest_run + 1)
        update["body"] = (
            f"{comment.body}\n\nSuggested fix (written for line "
            f"{comment.line_number}):\n{fence}\n{fix}\n{fence}"
        )
        update["suggested_fix"] = None
    return comment.model_copy(update=update)


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
            result.append(_snap(comment, nearest))
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
