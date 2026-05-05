"""
Tests for code parser service.
"""

import pytest

from services.code_parser import (
    DiffChunk,
    detect_language,
    get_extension,
    chunk_into_functions,
    parse_diff,
    parse_unified_diff,
)


class TestDetectLanguage:
    def test_detect_language_python(self):
        assert detect_language("src/app.py") == "python"
        assert detect_language("lib/utils.py") == "python"

    def test_detect_language_typescript(self):
        assert detect_language("src/components/Button.tsx") == "typescript"
        assert detect_language("src/index.ts") == "typescript"

    def test_detect_language_go(self):
        assert detect_language("main.go") == "go"
        assert detect_language("internal/handler.go") == "go"

    def test_detect_language_unknown(self):
        assert detect_language("unknown.xyz") == "unknown"

    def test_detect_language_with_shebang(self):
        content = "#!/usr/bin/env python3\ndef foo():\n    pass"
        assert detect_language("script.py", content) == "python"

    def test_extension_detection(self):
        assert get_extension("src/app.py") == ".py"
        assert get_extension("src/app.tsx") == ".tsx"
        assert get_extension("main.go") == ".go"


class TestDiffChunk:
    def test_diff_chunk_creation(self):
        chunk = DiffChunk(
            file_path="src/app.py",
            added_lines=["def new_function():", "    pass"],
            removed_lines=["def old_function():", "    pass"],
            context_lines=["# Main app"],
            language="python",
            chunk_type="function",
        )
        assert chunk.file_path == "src/app.py"
        assert chunk.language == "python"
        assert len(chunk.added_lines) == 2


class TestParseDiff:
    def test_parse_simple_diff(self):
        diff = """--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
+import new_module
 def old_function():
     pass
"""
        chunks = parse_diff(diff)

        assert len(chunks) > 0
        assert chunks[0].file_path == "src/app.py"
        assert chunks[0].language == "python"
        assert "import new_module" in "".join(chunks[0].added_lines)

    def test_parse_multi_file_diff(self):
        diff = """--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
+import new_module
 def foo():
--- a/src/utils.go
+++ b/src/utils.go
@@ -1,2 +1,3 @@
+func newFunc() {
"""
        chunks = parse_diff(diff)

        assert len(chunks) == 2
        assert chunks[0].file_path == "src/app.py"
        assert chunks[1].file_path == "src/utils.go"

    def test_parse_diff_with_hunk_header(self):
        diff = """--- a/src/app.py
+++ b/src/app.py
@@ -10,5 +10,8 @@
 def old_function():
+    new code
+    more code
+    extra code
"""
        chunks = parse_diff(diff)

        assert len(chunks) > 0
        assert "@@ -10,5 +10,8 @@" in chunks[-1].hunk_header


class TestChunkIntoFunctions:
    def test_chunk_python_functions(self):
        code = """def foo():
    return 1

def bar():
    return 2

class MyClass:
    pass
"""
        chunks = chunk_into_functions(code, "python")

        assert len(chunks) == 3
        assert "def foo():" in chunks[0]
        assert "def bar():" in chunks[1]
        assert "class MyClass:" in chunks[2]

    def test_chunk_javascript(self):
        code = """function foo() {
    return 1;
}

const bar = () => {
    return 2;
};
"""
        chunks = chunk_into_functions(code, "javascript")

        assert len(chunks) >= 1


class TestParseUnifiedDiff:
    def test_parse_unified_diff(self):
        diff = """--- a/file.py
+++ b/file.py
@@ -1,2 +1,3 @@
+new line
 original line
"""
        chunks = parse_unified_diff(diff)

        assert len(chunks) > 0
        assert chunks[0].language == "python"
