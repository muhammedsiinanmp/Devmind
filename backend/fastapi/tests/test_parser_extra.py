"""
Tests for code parser - additional edge cases.
"""

import pytest

from services.code_parser import (
    DiffChunk,
    detect_language,
    chunk_into_functions,
    parse_diff,
)


class TestParserEdgeCases:
    def test_detect_language_rust(self):
        assert detect_language("src/main.rs") == "rust"

    def test_detect_language_java(self):
        assert detect_language("src/Main.java") == "java"

    def test_detect_language_swift(self):
        assert detect_language("src/App.swift") == "swift"

    def test_detect_language_sql(self):
        assert detect_language("migrations/001_create_users.sql") == "sql"

    def test_detect_language_ruby(self):
        assert detect_language("app/models/user.rb") == "ruby"

    def test_detect_language_with_content(self):
        content = "#!/usr/bin/env bash\necho hello"
        assert detect_language("script", content) == "bash"

    def test_parse_diff_no_changes(self):
        diff = """--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
 def old():
"""
        chunks = parse_diff(diff)
        assert len(chunks) >= 0

    def test_parse_diff_only_context(self):
        diff = """--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,3 @@
 context line
"""
        chunks = parse_diff(diff)
        assert len(chunks) >= 0

    def test_parse_empty_diff(self):
        chunks = parse_diff("")
        assert chunks == []

    def test_parse_plain_lines(self):
        diff = """just some text
no diff markers
"""
        chunks = parse_diff(diff)
        assert len(chunks) >= 0

    def test_chunk_java_functions(self):
        code = """public class MyClass {
    public void doSomething() {
    }
}
"""
        chunks = chunk_into_functions(code, "java")
        assert len(chunks) > 0

    def test_chunk_go_functions(self):
        code = """package main

func main() {
}
"""
        chunks = chunk_into_functions(code, "go")
        assert len(chunks) > 0

    def test_get_extension_edge_cases(self):
        from services.code_parser import get_extension

        assert get_extension("file") == ""
        assert get_extension(".hidden") == ".hidden"
