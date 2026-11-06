"""
Split a large diff into batches of whole files that each fit one prompt.

Generated and vendored files (lockfiles, minified bundles, snapshots) are
skipped by a configurable glob list (``review_skip_patterns`` in
core/config.py). The remaining files are packed in diff order into batches
that fit the prompt's diff budget, so every file is reviewed rather than cut
by the budget. Files in batches beyond the batch cap are skipped and
reported.
"""

from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from services.prompt_builder import MAX_DIFF_LINES, file_render_cost

SKIP_GENERATED = "generated"
SKIP_BATCH_LIMIT = "batch_limit"
# Set by run_review_agent for batches unfinished at the review deadline.
SKIP_DEADLINE = "deadline"


@dataclass
class SkippedFile:
    file_path: str
    reason: str  # SKIP_GENERATED, SKIP_BATCH_LIMIT or SKIP_DEADLINE


@dataclass
class BatchPlan:
    """Batches of diff chunks to review, and the files each outcome covers."""

    batches: list[list] = field(default_factory=list)
    files_reviewed: list[str] = field(default_factory=list)
    files_skipped: list[SkippedFile] = field(default_factory=list)


def is_skipped_path(file_path: str, patterns: list[str]) -> bool:
    """True if the path, or the file name alone, matches a skip pattern."""
    name = file_path.rsplit("/", 1)[-1]
    return any(fnmatchcase(file_path, p) or fnmatchcase(name, p) for p in patterns)


def plan_batches(
    chunks: list,
    diff_budget: int,
    skip_patterns: list[str],
    max_batches: int,
    max_lines: int = MAX_DIFF_LINES,
) -> BatchPlan:
    """
    Pack the diff's files, in order, into batches that fit one prompt.

    A batch fits if its files' rendered lines total at most ``max_lines`` and
    their rendered tokens at most ``diff_budget``. A file too big for a batch
    on its own gets a batch to itself and is trimmed by the prompt's per-file
    caps, as before. A diff that fits in one batch gives exactly one batch
    holding all its chunks, so its prompt is unchanged.

    A diff with no files gives one empty batch (the agent still runs, as
    before); a diff whose files are all skipped gives no batch.
    """
    plan = BatchPlan()
    kept = []
    for chunk in chunks:
        if is_skipped_path(chunk.file_path, skip_patterns):
            plan.files_skipped.append(SkippedFile(chunk.file_path, SKIP_GENERATED))
        else:
            kept.append(chunk)

    if not kept:
        if not chunks:
            plan.batches.append([])
        return plan

    batches: list[list] = []
    current: list = []
    used_lines = used_tokens = 0
    for chunk in kept:
        lines, tokens = file_render_cost(chunk)
        if current and (
            used_lines + lines > max_lines or used_tokens + tokens > diff_budget
        ):
            batches.append(current)
            current, used_lines, used_tokens = [], 0, 0
        current.append(chunk)
        used_lines += lines
        used_tokens += tokens
    batches.append(current)

    plan.batches = batches[:max_batches]
    plan.files_reviewed = [c.file_path for batch in plan.batches for c in batch]
    plan.files_skipped += [
        SkippedFile(c.file_path, SKIP_BATCH_LIMIT)
        for batch in batches[max_batches:]
        for c in batch
    ]
    return plan
