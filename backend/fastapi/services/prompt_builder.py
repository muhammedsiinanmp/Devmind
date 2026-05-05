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
        diff_text = format_diff_chunks(context.diff_chunks)
        parts.append(diff_text)

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


def format_diff_chunks(chunks: list) -> str:
    """Format diff chunks for prompt."""
    lines = []
    for chunk in chunks:
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
    return "\n".join(lines)


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
