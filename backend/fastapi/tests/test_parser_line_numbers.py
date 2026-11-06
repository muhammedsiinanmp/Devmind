"""
Tests for new-file line numbers recorded by the diff parser.
"""

from services.code_parser import parse_diff


def _numbered(chunk, kind):
    return [
        (line.new_line, line.content)
        for hunk in chunk.hunks
        for line in hunk.lines
        if line.kind == kind
    ]


class TestHunkLineNumbers:
    def test_added_and_context_lines_get_new_file_numbers(self):
        diff = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -10,4 +10,5 @@ def handler():
 a = 1
-b = 2
+b = 3
+c = 4
 d = 5
 e = 6
"""
        chunks = parse_diff(diff)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert _numbered(chunk, "context") == [
            (10, "a = 1"),
            (13, "d = 5"),
            (14, "e = 6"),
        ]
        assert _numbered(chunk, "added") == [(11, "b = 3"), (12, "c = 4")]
        removed = [ln for h in chunk.hunks for ln in h.lines if ln.kind == "removed"]
        assert [(ln.old_line, ln.new_line, ln.content) for ln in removed] == [
            (11, None, "b = 2")
        ]

    def test_multi_hunk_file_numbers_each_hunk_from_its_header(self):
        diff = """--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
 import os
+import sys

 x = 1
@@ -40,3 +41,3 @@ def run():
 y = 2
-z = 3
+z = 4
 return z
"""
        chunks = parse_diff(diff)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert len(chunk.hunks) == 2
        assert [h.new_start for h in chunk.hunks] == [1, 41]
        assert _numbered(chunk, "added") == [(2, "import sys"), (42, "z = 4")]
        assert _numbered(chunk, "context") == [
            (1, "import os"),
            (3, ""),
            (4, "x = 1"),
            (41, "y = 2"),
            (43, "return z"),
        ]
        assert chunk.added_lines == ["import sys", "z = 4"]
        assert chunk.removed_lines == ["z = 3"]

    def test_deleted_file_uses_old_path_and_has_no_new_lines(self):
        diff = """diff --git a/src/old.py b/src/old.py
deleted file mode 100644
index 3b18e51..0000000
--- a/src/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-print("a")
-print("b")
"""
        chunks = parse_diff(diff)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.file_path == "src/old.py"
        assert chunk.removed_lines == ['print("a")', 'print("b")']
        assert all(ln.new_line is None for h in chunk.hunks for ln in h.lines)

    def test_new_file_numbers_from_one(self):
        diff = """diff --git a/src/new.py b/src/new.py
new file mode 100644
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+one
+two
"""
        chunks = parse_diff(diff)

        assert chunks[0].file_path == "src/new.py"
        assert _numbered(chunks[0], "added") == [(1, "one"), (2, "two")]

    def test_renamed_file_uses_new_path_and_keeps_old_path(self):
        diff = """diff --git a/src/before.py b/src/after.py
similarity index 90%
rename from src/before.py
rename to src/after.py
--- a/src/before.py
+++ b/src/after.py
@@ -5,2 +5,2 @@
 keep = True
-name = "before"
+name = "after"
"""
        chunks = parse_diff(diff)

        assert len(chunks) == 1
        assert chunks[0].file_path == "src/after.py"
        assert chunks[0].old_path == "src/before.py"
        assert _numbered(chunks[0], "added") == [(6, 'name = "after"')]

    def test_no_newline_marker_is_not_a_line(self):
        diff = """--- a/a.txt
+++ b/a.txt
@@ -1,2 +1,2 @@
 first
-second
\\ No newline at end of file
+second
\\ No newline at end of file
--- a/b.txt
+++ b/b.txt
@@ -3 +3,2 @@
 third
+fourth
"""
        chunks = parse_diff(diff)

        assert [c.file_path for c in chunks] == ["a.txt", "b.txt"]
        a, b = chunks
        assert _numbered(a, "added") == [(2, "second")]
        assert _numbered(a, "context") == [(1, "first")]
        assert all("No newline" not in ln.content for h in a.hunks for ln in h.lines)
        assert _numbered(b, "added") == [(4, "fourth")]

    def test_content_lines_that_look_like_file_headers(self):
        # A removed SQL comment "-- x" renders as "--- x"; an added "++ y" as "+++ y".
        diff = """--- a/q.sql
+++ b/q.sql
@@ -1,2 +1,2 @@
--- old comment
+++ new comment
 SELECT 1;
"""
        chunks = parse_diff(diff)

        assert len(chunks) == 1
        assert chunks[0].file_path == "q.sql"
        assert chunks[0].removed_lines == ["-- old comment"]
        assert _numbered(chunks[0], "added") == [(1, "++ new comment")]
        assert _numbered(chunks[0], "context") == [(2, "SELECT 1;")]

    def test_crlf_blank_context_line_does_not_end_the_hunk(self):
        # A blank context line whose leading space was stripped arrives as "\r".
        diff = (
            "--- a/win.py\r\n"
            "+++ b/win.py\r\n"
            "@@ -1,3 +1,4 @@\r\n"
            " a = 1\r\n"
            "\r\n"
            "+b = 2\r\n"
            " c = 3\r\n"
        )
        chunks = parse_diff(diff)

        assert len(chunks) == 1
        assert chunks[0].file_path == "win.py"
        assert _numbered(chunks[0], "added") == [(3, "b = 2")]
        assert _numbered(chunks[0], "context") == [(1, "a = 1"), (2, ""), (4, "c = 3")]
