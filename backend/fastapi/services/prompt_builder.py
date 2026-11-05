"""
Prompt builder for assembling review prompts.

Builds prompts with context priority and enforces token budget.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import tiktoken

    _tiktoken_available = True
except ImportError:
    _tiktoken_available = False


MAX_TOKENS = 8192
# Diff rendering limits. The diff is rendered first and the retrieved patterns
# only get the budget it leaves, so it must not take the whole prompt.
MAX_HUNK_LINES = 120
MAX_FILE_LINES = 200
MAX_DIFF_LINES = 600
MAX_LINE_CHARS = 300
# Room kept free in the prompt besides the diff and the predicted context sections.
PROMPT_MARGIN_TOKENS = 200


REVIEW_SYSTEM_PROMPT = """You are an expert code reviewer AI. Your task is to review code changes and provide constructive, actionable feedback.

Guidelines:
1. Focus on security, correctness, and code quality
2. Provide specific suggestions with code examples when possible
3. Be concise but thorough
4. Flag critical issues immediately
5. Suggest improvements politely

Review format:
- Issue: Description
- Severity: critical/high/medium/low
- Location: file:line
- Suggestion: How to fix

Line numbers:
- Diff lines are shown as "L<n> + code" (added) or "L<n>   code" (unchanged context),
  where <n> is the line number in the new file. Removed lines ("- code") have no number.
- Set line_number to the <n> of the added or context line the comment is about.
  Never use a line number that is not shown in the diff.
"""


@dataclass
class PromptContext:
    """Context for building review prompts."""

    diff_chunks: list = field(default_factory=list)
    similar_patterns: list = field(default_factory=list)
    quality_patterns: list = field(default_factory=list)
    past_reviews: list = field(default_factory=list)
    repo_conventions: Optional[str] = None


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """
    Count tokens using tiktoken.

    Args:
        text: Text to count
        encoding_name: Token encoding (default: cl100k_base for GPT-4)

    Returns:
        Token count
    """
    if not _tiktoken_available:
        logger.warning("tiktoken not available, using rough estimate")
        return len(text) // 4

    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception:
        return len(text) // 4


def truncate_to_budget(text: str, max_tokens: int, priority: list[int]) -> str:
    """
    Truncate text to stay within token budget.

    Args:
        text: Text to truncate
        max_tokens: Maximum tokens allowed
        priority: List of truncation priorities (1 = highest priority to keep)

    Returns:
        Truncated text
    """
    tokens = count_tokens(text)
    if tokens <= max_tokens:
        return text

    lines = text.split("\n")
    if not lines:
        return text

    target_tokens = max_tokens
    while lines:
        truncated = "\n".join(lines)
        tokens = count_tokens(truncated)
        if tokens <= target_tokens:
            return truncated

        lines = lines[:-1]

    return ""


def _context_sections_tokens(context: PromptContext) -> int:
    """
    Tokens to keep free for the non-diff sections.

    Each section reserves its size (up to the cap applied below) or, if more,
    the free budget build_review_prompt requires before adding it.
    """
    header = 20
    sections = [
        (context.similar_patterns, format_patterns, 2000, 500),
        (context.quality_patterns, format_patterns, 1500, 300),
        (context.past_reviews, format_past_reviews, 1000, 200),
    ]
    total = 0
    for items, formatter, cap, gate in sections:
        if items:
            size = header + min(count_tokens(formatter(items)), cap)
            total += max(size, gate + 1)
    if context.repo_conventions:
        size = header + min(count_tokens(context.repo_conventions), 500)
        total += max(size, 101)
    return total


def build_review_prompt(
    context: PromptContext,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """
    Build review prompt with context and token budget enforcement.

    Context priority (highest to lowest):
    1. Diff itself
    2. Security-relevant similar patterns
    3. Quality patterns
    4. Past review summaries
    5. Repo conventions

    Args:
        context: PromptContext with all context parts
        max_tokens: Maximum tokens (default: 8192)

    Returns:
        Complete prompt string within token budget
    """
    parts: list[str] = []

    parts.append(REVIEW_SYSTEM_PROMPT)
    parts.append("\n\n=== CODE CHANGES ===\n")

    if context.diff_chunks:
        # The diff gets whatever the context sections below will not use, but
        # never less than half the prompt, since it has the highest priority.
        diff_budget = max(
            max_tokens
            - count_tokens("\n".join(parts))
            - _context_sections_tokens(context)
            - PROMPT_MARGIN_TOKENS,
            max_tokens // 2,
        )
        parts.append(render_diff(context.diff_chunks, diff_budget))

    diff_tokens = count_tokens("\n".join(parts))

    remaining_budget = max_tokens - diff_tokens - 100

    if remaining_budget <= 0:
        return truncate_to_budget("\n".join(parts), max_tokens, [1, 2, 3])

    if context.similar_patterns and remaining_budget > 500:
        parts.append("\n\n=== SIMILAR SECURITY PATTERNS ===\n")
        patterns_text = format_patterns(context.similar_patterns)
        truncated = truncate_to_budget(patterns_text, min(remaining_budget, 2000), [1])
        parts.append(truncated)

    remaining_budget = max_tokens - count_tokens("\n".join(parts))

    if context.quality_patterns and remaining_budget > 300:
        parts.append("\n\n=== QUALITY PATTERNS ===\n")
        patterns_text = format_patterns(context.quality_patterns)
        truncated = truncate_to_budget(patterns_text, min(remaining_budget, 1500), [2])
        parts.append(truncated)

    remaining_budget = max_tokens - count_tokens("\n".join(parts))

    if context.past_reviews and remaining_budget > 200:
        parts.append("\n\n=== PAST REVIEWS ===\n")
        reviews_text = format_past_reviews(context.past_reviews)
        truncated = truncate_to_budget(reviews_text, min(remaining_budget, 1000), [3])
        parts.append(truncated)

    remaining_budget = max_tokens - count_tokens("\n".join(parts))

    if context.repo_conventions and remaining_budget > 100:
        parts.append("\n\n=== REPO CONVENTIONS ===\n")
        truncated = truncate_to_budget(context.repo_conventions, remaining_budget, [4])
        parts.append(truncated)

    final_prompt = "\n".join(parts)

    if count_tokens(final_prompt) > max_tokens:
        logger.warning("Prompt exceeds budget, truncating")
        final_prompt = truncate_to_budget(final_prompt, max_tokens, [1, 2, 3, 4])

    return final_prompt


def _distances_to_change(lines: list) -> list[int]:
    """Distance from each line to the nearest added or removed line (two passes)."""
    n = len(lines)
    distances = [n] * n
    last: Optional[int] = None
    for i, line in enumerate(lines):
        if line.kind != "context":
            last = i
        if last is not None:
            distances[i] = i - last
    last = None
    for i in range(n - 1, -1, -1):
        if lines[i].kind != "context":
            last = i
        if last is not None:
            distances[i] = min(distances[i], last - i)
    return distances


def _ranked_file_lines(
    hunks: list,
    max_hunk_lines: int = MAX_HUNK_LINES,
    max_file_lines: int = MAX_FILE_LINES,
) -> list[tuple[int, int, int, int]]:
    """
    A file's lines as ``(rank, index, hunk, index)``, best first, after the caps.

    Rank 0 is an added line, 1 a removed line, and 2 + distance a context line,
    so context lines farthest from a change are dropped first.
    """
    ranked: list[tuple[int, int, int, int]] = []
    for h, hunk in enumerate(hunks):
        distances = _distances_to_change(hunk.lines)
        ranks = sorted(
            (
                {"added": 0, "removed": 1}.get(line.kind, 2 + distances[i]),
                i,
                h,
                i,
            )
            for i, line in enumerate(hunk.lines)
        )
        ranked.extend(ranks[:max_hunk_lines])
    ranked.sort()
    return ranked[:max_file_lines]


def _keep_sets(hunks: list, ranked: list[tuple[int, int, int, int]]) -> list[set[int]]:
    keep: list[set[int]] = [set() for _ in hunks]
    for _, _, h, i in ranked:
        keep[h].add(i)
    return keep


def select_hunk_lines(
    hunks: list,
    max_hunk_lines: int = MAX_HUNK_LINES,
    max_file_lines: int = MAX_FILE_LINES,
) -> list[set[int]]:
    """
    Pick which lines of one file's hunks fit the prompt.

    Context lines farthest from a change are dropped first, then removed
    lines, then added lines. Returns the kept line indices of each hunk.
    """
    return _keep_sets(hunks, _ranked_file_lines(hunks, max_hunk_lines, max_file_lines))


def _fair_share(demands: list[int], budget: int) -> list[int]:
    """Split ``budget`` evenly; files needing less than a share free it for others."""
    alloc = [0] * len(demands)
    remaining = budget
    active = [i for i, demand in enumerate(demands) if demand > 0]
    while remaining > 0 and active:
        share = remaining // len(active)
        if share == 0:
            for i in active[:remaining]:
                alloc[i] += 1
            break
        still_wanting = []
        for i in active:
            given = min(share, demands[i] - alloc[i])
            alloc[i] += given
            remaining -= given
            if alloc[i] < demands[i]:
                still_wanting.append(i)
        active = still_wanting
    return alloc


def select_diff_lines(files: list[list], max_lines: int) -> list[list[set[int]]]:
    """
    Pick the lines of every file that fit in ``max_lines``.

    The budget goes to added lines first, then removed lines, then context,
    and each of those is shared evenly between files. Early files therefore
    can't use up the budget with context lines before later files show their
    changes.
    """
    ranked = [_ranked_file_lines(hunks) for hunks in files]
    alloc = [0] * len(files)
    remaining = max_lines
    for tier in (0, 1, 2):
        demands = [
            sum(1 for rank, *_ in lines if min(rank, 2) == tier) for lines in ranked
        ]
        given = _fair_share(demands, remaining)
        for f, amount in enumerate(given):
            alloc[f] += amount
        remaining -= sum(given)
    return [
        _keep_sets(hunks, lines[:count])
        for hunks, lines, count in zip(files, ranked, alloc)
    ]


def format_hunk_lines(hunk, keep: Optional[set[int]] = None) -> list[str]:
    """
    Render a hunk with new-file line numbers.

    Added lines render as ``L42 + code`` and context lines as ``L41   code``.
    Removed lines have no new-file number and render as ``      - code``.
    Lines not in ``keep`` are replaced by ``... N lines omitted``.
    """
    if keep is None:
        keep = set(range(len(hunk.lines)))
    width = len(str(max((ln.new_line or 0 for ln in hunk.lines), default=0))) + 1
    rendered = []
    skipped = 0
    for i, line in enumerate(hunk.lines):
        if i not in keep:
            skipped += 1
            continue
        if skipped:
            rendered.append(f"... {skipped} lines omitted")
            skipped = 0
        marker = {"added": "+", "removed": "-"}.get(line.kind, " ")
        number = f"L{line.new_line}" if line.new_line is not None else ""
        content = line.content
        if len(content) > MAX_LINE_CHARS:
            content = content[:MAX_LINE_CHARS] + " [line cut]"
        rendered.append(f"{number:<{width}} {marker} {content}")
    if skipped:
        rendered.append(f"... {skipped} lines omitted")
    return rendered


def format_diff_chunks(chunks: list, max_lines: int = MAX_DIFF_LINES) -> str:
    """
    Format diff chunks for prompt.

    At most MAX_HUNK_LINES per hunk, MAX_FILE_LINES per file and ``max_lines``
    in total are rendered, chosen by ``select_diff_lines``. Files with no line
    left are not shown, and a final ``[N files / M lines omitted from this
    diff]`` line reports what was cut.
    """
    numbered = [c for c in chunks if getattr(c, "hunks", None)]
    selections = select_diff_lines([c.hunks for c in numbered], max_lines)
    keep_by_chunk = {id(c): keep for c, keep in zip(numbered, selections)}

    lines = []
    omitted_files = 0
    omitted_lines = 0
    for chunk in chunks:
        keep = keep_by_chunk.get(id(chunk))
        if keep is not None:
            hunks = chunk.hunks
            kept = sum(len(k) for k in keep)
            omitted_lines += sum(len(hunk.lines) for hunk in hunks) - kept
            if kept == 0:
                omitted_files += 1
                continue
            lines.append(f"File: {chunk.file_path}")
            lines.append(f"Language: {chunk.language}")
            for hunk, hunk_keep in zip(hunks, keep):
                if hunk_keep:
                    lines.append(f"Hunk: {hunk.header}")
                    lines.extend(format_hunk_lines(hunk, hunk_keep))
            lines.append("")
            continue
        lines.append(f"File: {chunk.file_path}")
        lines.append(f"Language: {chunk.language}")
        if chunk.hunk_header:
            lines.append(f"Hunk: {chunk.hunk_header}")
        if chunk.added_lines:
            lines.append("Added:")
            lines.extend(chunk.added_lines[:50])
        if chunk.removed_lines:
            lines.append("Removed:")
            lines.extend(chunk.removed_lines[:50])
        lines.append("")
    if omitted_files or omitted_lines:
        lines.append(
            f"[{omitted_files} files / {omitted_lines} lines omitted from this diff]"
        )
    return "\n".join(lines)


def render_diff(chunks: list, max_tokens: int) -> str:
    """
    Render the diff in at most ``max_tokens``.

    Shrinks the line budget until the rendering fits, so every file keeps its
    fair share. If file and hunk headers alone are too big, the text is cut
    at a line boundary as a last resort.
    """
    max_lines = MAX_DIFF_LINES
    text = format_diff_chunks(chunks, max_lines)
    for _ in range(6):
        tokens = count_tokens(text)
        if tokens <= max_tokens:
            return text
        max_lines = int(max_lines * max_tokens / tokens * 0.95)
        if max_lines < 1:
            break
        text = format_diff_chunks(chunks, max_lines)
    return fit_diff_to_tokens(text, max_tokens)


def fit_diff_to_tokens(diff_text: str, max_tokens: int) -> str:
    """
    Cut the rendered diff at a line boundary so it uses at most ``max_tokens``,
    leaving room in the prompt for retrieved patterns and other context.
    """
    if count_tokens(diff_text) <= max_tokens:
        return diff_text
    marker_budget = 40
    diff_lines = diff_text.split("\n")
    summary = None
    if diff_lines[-1].endswith("omitted from this diff]"):
        summary = diff_lines.pop()
    kept: list[str] = []
    used = 0
    for line in diff_lines:
        cost = count_tokens(line) + 1
        if used + cost > max_tokens - marker_budget:
            break
        kept.append(line)
        used += cost
    dropped = len(diff_lines) - len(kept)
    kept.append(f"[{dropped} more diff lines omitted to fit the prompt]")
    if summary:
        kept.append(summary)
    return "\n".join(kept)


def format_patterns(patterns: list) -> str:
    """Format code patterns for prompt."""
    lines = []
    for i, pattern in enumerate(patterns[:10], 1):
        lines.append(f"{i}. {pattern}")
    return "\n".join(lines)


def format_past_reviews(reviews: list) -> str:
    """Format past reviews for prompt."""
    lines = []
    for i, review in enumerate(reviews[:5], 1):
        lines.append(f"{i}. {review}")
    return "\n".join(lines)
