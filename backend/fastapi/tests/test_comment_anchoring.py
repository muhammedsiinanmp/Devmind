"""
Tests for anchoring review comments to lines that exist in the PR diff.
"""

from models.review import ReviewComment
from services.code_parser import parse_diff
from services.comment_anchoring import anchor_comments

# New-file lines in the diff: 10 (context), 11-12 (added) in hunk one,
# 50 (added) in hunk two. Nothing else in app.py is part of the diff.
DIFF = """--- a/src/app.py
+++ b/src/app.py
@@ -10,2 +10,3 @@ def handler():
 a = 1
-b = 2
+b = 3
+c = 4
@@ -49 +50 @@
-old = True
+new = True
"""


def _comment(line_number, file_path="src/app.py", body="issue"):
    return ReviewComment(
        file_path=file_path,
        line_number=line_number,
        category="quality",
        severity="warning",
        body=body,
    )


class TestSnapStaysInOneHunk:
    # Hunk one covers new lines 1-3, hunk two covers 5-7; line 4 is in neither.
    DIFF = """--- a/m.py
+++ b/m.py
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
@@ -5,3 +5,3 @@
 five
-six
+SIX
 seven
"""

    def test_line_between_two_hunks_is_unanchored(self):
        comments, stats = anchor_comments(
            parse_diff(self.DIFF), [_comment(4, file_path="m.py")]
        )

        assert comments[0].line_number == 0
        assert (stats.anchored, stats.snapped, stats.unanchored) == (0, 0, 1)

    def test_line_near_only_one_hunk_still_snaps(self):
        comments, stats = anchor_comments(
            parse_diff(self.DIFF), [_comment(9, file_path="m.py")]
        )

        assert comments[0].line_number == 7
        assert stats.snapped == 1


class TestSnappedSuggestedFix:
    def test_snapped_comment_loses_suggestion_but_keeps_fix_as_text(self):
        comment = _comment(14).model_copy(
            update={"suggested_fix": "c = compute()", "body": "Use compute()"}
        )

        comments, stats = anchor_comments(parse_diff(DIFF), [comment])

        assert stats.snapped == 1
        assert comments[0].line_number == 12
        assert comments[0].suggested_fix is None
        assert comments[0].body.startswith("Use compute()")
        assert "c = compute()" in comments[0].body
        assert "```suggestion" not in comments[0].body

    def test_anchored_comment_keeps_its_suggested_fix(self):
        comment = _comment(11).model_copy(update={"suggested_fix": "b = 4"})

        comments, _ = anchor_comments(parse_diff(DIFF), [comment])

        assert comments[0].suggested_fix == "b = 4"
        assert comments[0].body == "issue"


class TestAnchorComments:
    def test_comment_on_diff_line_is_kept_unchanged(self):
        comments, stats = anchor_comments(
            parse_diff(DIFF), [_comment(11), _comment(10)]
        )

        assert [c.line_number for c in comments] == [11, 10]
        assert (stats.anchored, stats.snapped, stats.unanchored) == (2, 0, 0)

    def test_comment_two_lines_from_changed_line_is_moved_to_it(self):
        comments, stats = anchor_comments(
            parse_diff(DIFF), [_comment(14), _comment(48)]
        )

        assert [c.line_number for c in comments] == [12, 50]
        assert (stats.anchored, stats.snapped, stats.unanchored) == (0, 2, 0)

    def test_comment_outside_diff_is_never_inline(self):
        comments, stats = anchor_comments(
            parse_diff(DIFF),
            [
                _comment(30),  # far from both hunks
                _comment(16),  # four lines past hunk one
                _comment(12, file_path="src/other.py"),  # file not in diff
                _comment(0),  # model gave no line
            ],
        )

        assert len(comments) == 4
        assert all(c.line_number == 0 for c in comments)
        assert [c.body for c in comments] == ["issue"] * 4
        assert (stats.anchored, stats.snapped, stats.unanchored) == (0, 0, 4)

    def test_snapping_picks_the_nearest_line(self):
        # 13 is one line from 12 (hunk one) and far from 50 (hunk two).
        comments, _ = anchor_comments(parse_diff(DIFF), [_comment(13), _comment(9)])

        assert [c.line_number for c in comments] == [12, 10]

    def test_lines_of_a_deleted_file_are_not_anchorable(self):
        diff = """--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
"""
        comments, stats = anchor_comments(parse_diff(diff), [_comment(1, "gone.py")])

        assert comments[0].line_number == 0
        assert stats.unanchored == 1

    def test_no_comments(self):
        comments, stats = anchor_comments(parse_diff(DIFF), [])

        assert comments == []
        assert (stats.anchored, stats.snapped, stats.unanchored) == (0, 0, 0)
