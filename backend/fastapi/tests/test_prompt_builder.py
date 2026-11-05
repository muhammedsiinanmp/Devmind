"""
Tests for prompt builder service.
"""

from services.prompt_builder import (
    PromptContext,
    REVIEW_SYSTEM_PROMPT,
    count_tokens,
    truncate_to_budget,
    build_review_prompt,
    format_diff_chunks,
    format_patterns,
    format_past_reviews,
)


class TestPromptContext:
    def test_prompt_context_defaults(self):
        context = PromptContext()
        assert context.diff_chunks == []
        assert context.similar_patterns == []
        assert context.quality_patterns == []
        assert context.past_reviews == []


class TestTokenCounting:
    def test_count_tokens_with_tiktoken(self):
        text = "def hello():\n    print('world')"
        count = count_tokens(text)
        assert count > 0

    def test_count_tokens_empty(self):
        count = count_tokens("")
        assert count == 0

    def test_count_tokens_long_text(self):
        text = "x" * 1000
        count = count_tokens(text)
        assert count > 0


class TestTruncateToBudget:
    def test_truncate_short_text(self):
        text = "short text"
        result = truncate_to_budget(text, 100, [1])
        assert result == text

    def test_truncate_exceeds_budget(self):
        text = "a" * 1000
        result = truncate_to_budget(text, 100, [1])
        assert len(result) < len(text)


class TestBuildReviewPrompt:
    def test_build_simple_prompt(self):
        context = PromptContext()
        prompt = build_review_prompt(context)

        assert REVIEW_SYSTEM_PROMPT in prompt
        assert "CODE CHANGES" in prompt

    def test_build_prompt_with_diff_chunks(self):
        from services.code_parser import DiffChunk

        chunk = DiffChunk(
            file_path="src/app.py",
            added_lines=["def new_func():", "    pass"],
            removed_lines=[],
            context_lines=[],
            language="python",
            chunk_type="function",
        )

        context = PromptContext(diff_chunks=[chunk])
        prompt = build_review_prompt(context)

        assert "src/app.py" in prompt
        assert chunk.added_lines[0] in prompt

    def test_build_prompt_with_similar_patterns(self):
        context = PromptContext(
            similar_patterns=["SQL injection vulnerability", "XSS pattern"]
        )
        prompt = build_review_prompt(context)

        assert "SIMILAR SECURITY PATTERNS" in prompt

    def test_build_prompt_with_quality_patterns(self):
        context = PromptContext(
            quality_patterns=["Missing error handling", "Use f-strings"]
        )
        prompt = build_review_prompt(context)

        assert "QUALITY PATTERNS" in prompt

    def test_build_prompt_with_past_reviews(self):
        context = PromptContext(past_reviews=["Use async/await", "Add type hints"])
        prompt = build_review_prompt(context)

        assert "PAST REVIEWS" in prompt

    def test_build_prompt_with_conventions(self):
        context = PromptContext(repo_conventions="Use PEP 8 style")
        prompt = build_review_prompt(context)

        assert "REPO CONVENTIONS" in prompt

    def test_prompt_respects_max_tokens(self):
        large_diff = "+" * 10000

        class MockChunk:
            file_path = "test.py"
            added_lines = [large_diff]
            removed_lines = []
            context_lines = []
            language = "python"
            chunk_type = "file"
            hunk_header = ""

        context = PromptContext(diff_chunks=[MockChunk()])
        prompt = build_review_prompt(context, max_tokens=8192)

        assert count_tokens(prompt) <= 8192


class TestFormatting:
    def test_format_diff_chunks(self):
        from services.code_parser import DiffChunk

        chunk = DiffChunk(
            file_path="src/app.py",
            added_lines=["def new():", "    pass"],
            removed_lines=[],
            context_lines=[],
            language="python",
            chunk_type="function",
        )

        result = format_diff_chunks([chunk])

        assert "src/app.py" in result
        assert "def new():" in result

    def test_format_patterns(self):
        patterns = ["Pattern 1", "Pattern 2"]
        result = format_patterns(patterns)

        assert "Pattern 1" in result
        assert "Pattern 2" in result

    def test_format_past_reviews(self):
        reviews = ["Review 1", "Review 2"]
        result = format_past_reviews(reviews)

        assert "Review 1" in result
        assert "Review 2" in result


class TestSystemPrompt:
    def test_system_prompt_exists(self):
        assert REVIEW_SYSTEM_PROMPT is not None
        assert len(REVIEW_SYSTEM_PROMPT) > 0

    def test_system_prompt_contains_guidelines(self):
        assert "security" in REVIEW_SYSTEM_PROMPT.lower()
        assert "quality" in REVIEW_SYSTEM_PROMPT.lower()


class TestDiffLineNumbersInPrompt:
    DIFF = """--- a/src/app.py
+++ b/src/app.py
@@ -40,3 +40,4 @@ def run():
 y = 2
-z = 3
+z = 4
+w = 5
 return z
"""

    def test_added_and_context_lines_show_new_file_numbers(self):
        from services.code_parser import parse_diff

        lines = format_diff_chunks(parse_diff(self.DIFF)).split("\n")

        assert "L40   y = 2" in lines
        assert "L41 + z = 4" in lines
        assert "L42 + w = 5" in lines
        assert "L43   return z" in lines

    def test_removed_lines_have_no_new_file_number(self):
        from services.code_parser import parse_diff

        lines = format_diff_chunks(parse_diff(self.DIFF)).split("\n")

        removed = [ln for ln in lines if ln.endswith("- z = 3")]
        assert len(removed) == 1
        assert not removed[0].lstrip().startswith("L")

    def test_full_prompt_includes_numbered_diff_and_instruction(self):
        from services.code_parser import parse_diff

        prompt = build_review_prompt(PromptContext(diff_chunks=parse_diff(self.DIFF)))

        assert "L41 + z = 4" in prompt
        assert "line_number" in prompt
