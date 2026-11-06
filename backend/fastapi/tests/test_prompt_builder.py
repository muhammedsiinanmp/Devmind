"""
Tests for prompt builder service.
"""

import re

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


def _file_diff(path, lines, start=1):
    """One-hunk diff; ``lines`` is a list of ("+" or " ", text)."""
    added = sum(1 for kind, _ in lines if kind == "+")
    old_count = len(lines) - added
    body = "".join(f"{kind}{text}\n" for kind, text in lines)
    return (
        f"--- a/{path}\n+++ b/{path}\n"
        f"@@ -{start},{old_count} +{start},{len(lines)} @@\n{body}"
    )


def _numbered_lines(text):
    return [ln for ln in text.split("\n") if re.match(r"L\d+ ", ln)]


class TestDiffBudget:
    def test_hunk_is_capped_at_120_lines_with_marker(self):
        from services.code_parser import parse_diff

        diff = _file_diff("big.py", [("+", f"x{i} = {i}") for i in range(200)])

        result = format_diff_chunks(parse_diff(diff))

        assert len(_numbered_lines(result)) == 120
        assert "... 80 lines omitted" in result

    def test_context_lines_are_trimmed_before_added_lines(self):
        from services.code_parser import parse_diff

        lines = [(" ", f"ctx{i}") for i in range(75)]
        lines += [("+", f"new{i}") for i in range(30)]
        lines += [(" ", f"ctx{i}") for i in range(75, 150)]
        result = format_diff_chunks(parse_diff(_file_diff("mid.py", lines)))

        rendered = "\n".join(_numbered_lines(result))
        assert all(f"+ new{i}" in rendered for i in range(30))
        assert len(_numbered_lines(result)) == 120
        # The context kept is the context next to the change.
        assert "ctx74" in rendered and "ctx75" in rendered
        assert "ctx0\n" not in rendered + "\n"

    def test_total_budget_is_shared_evenly_between_files(self):
        from services.code_parser import parse_diff

        diff = "".join(
            _file_diff(f"f{n}.py", [("+", f"v{i} = {i}") for i in range(100)])
            for n in range(5)
        )

        result = format_diff_chunks(parse_diff(diff), max_lines=200)

        for n in range(5):
            section = result.split(f"File: f{n}.py")[1].split("File: ")[0]
            assert len(_numbered_lines(section)) == 40
            assert "+ v0 = 0" in section
        assert "[0 files / 300 lines omitted from this diff]" in result

    def test_files_past_a_tiny_budget_are_reported_as_omitted(self):
        from services.code_parser import parse_diff

        diff = "".join(
            _file_diff(f"f{n}.py", [("+", f"v{i} = {i}") for i in range(10)])
            for n in range(5)
        )

        result = format_diff_chunks(parse_diff(diff), max_lines=3)

        assert len(_numbered_lines(result)) == 3
        assert "[2 files / 47 lines omitted from this diff]" in result

    def test_early_context_does_not_starve_later_added_lines(self):
        from services.code_parser import parse_diff

        diff = ""
        for n in range(11):
            lines = [(" ", f"    ctx_{n}_{i} = keep_this_line({i})") for i in range(60)]
            lines += [("+", f"    add_{n}_{i} = changed_line({i})") for i in range(20)]
            lines += [
                (" ", f"    tail_{n}_{i} = keep_this_line({i})") for i in range(60)
            ]
            diff += _file_diff(f"pkg/file_{n}.py", lines, start=1)
        context = PromptContext(
            diff_chunks=parse_diff(diff),
            similar_patterns=["PATTERN-MARKER: use parameterized queries"],
        )

        prompt = build_review_prompt(context)

        assert count_tokens(prompt) <= 8192
        assert "PATTERN-MARKER: use parameterized queries" in prompt
        for n in range(11):
            assert f"File: pkg/file_{n}.py" in prompt
            assert f"+     add_{n}_0 = changed_line(0)" in prompt

    def test_diff_uses_budget_the_rag_sections_leave_unused(self):
        from services.code_parser import parse_diff

        diff = "".join(
            _file_diff(
                f"f{n}.py",
                [("+", f"value_{n}_{i} = compute(item_{i})") for i in range(120)],
            )
            for n in range(10)
        )
        chunks = parse_diff(diff)
        big_patterns = [f"pattern {i}: " + "word " * 150 for i in range(10)]

        alone = build_review_prompt(PromptContext(diff_chunks=chunks))
        with_rag = build_review_prompt(
            PromptContext(diff_chunks=chunks, similar_patterns=big_patterns)
        )

        assert count_tokens(alone) <= 8192 and count_tokens(with_rag) <= 8192
        assert "SIMILAR SECURITY PATTERNS" in with_rag
        assert len(_numbered_lines(alone)) > len(_numbered_lines(with_rag))
        assert count_tokens(alone) > 6500

    def test_line_selection_is_fast_on_a_huge_hunk(self):
        import time

        from services.code_parser import DiffHunk, DiffLine
        from services.prompt_builder import select_hunk_lines

        lines = []
        for i in range(16000):
            kind = "added" if i % 2 else "context"
            lines.append(DiffLine(kind, f"line {i}", new_line=i + 1))
        hunk = DiffHunk(header="@@ -1,8000 +1,16000 @@", new_start=1, lines=lines)

        start = time.perf_counter()
        keep = select_hunk_lines([hunk])
        elapsed = time.perf_counter() - start

        assert sum(len(k) for k in keep) == 120
        assert elapsed < 1.0

    def test_medium_diff_keeps_similar_patterns_in_prompt(self):
        from services.code_parser import parse_diff

        diff = ""
        for n in range(11):
            lines = []
            for i in range(40):
                lines.append(
                    (" ", f"    existing_{i} = load_record(record_id_{i}, cache)")
                )
                lines.append(
                    ("+", f"    updated_{i} = transform_record(existing_{i}, opts)")
                )
            diff += _file_diff(f"pkg/module_{n}.py", lines, start=10)
        context = PromptContext(
            diff_chunks=parse_diff(diff),
            similar_patterns=["PATTERN-MARKER: use parameterized queries"],
        )

        prompt = build_review_prompt(context)

        assert count_tokens(prompt) <= 8192
        assert "SIMILAR SECURITY PATTERNS" in prompt
        assert "PATTERN-MARKER: use parameterized queries" in prompt
        assert "lines omitted from this diff]" in prompt
        for n in range(11):
            assert f"File: pkg/module_{n}.py" in prompt
