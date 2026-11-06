"""
Unit tests for the eval matcher: how agent findings are scored against
labeled expected findings (match, partial, miss, extra) and how the run-level
metrics are computed.
"""

import pytest

from evals.matcher import (
    Expected,
    aggregate,
    diff_hunks,
    match_case,
    new_side_lines,
    normalize_category,
    normalize_path,
)

DIFF = """\
diff --git a/app/users.py b/app/users.py
index 1111111..2222222 100644
--- a/app/users.py
+++ b/app/users.py
@@ -10,3 +10,5 @@ def get_user(db, user_id):
     cursor = db.cursor()
-    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
+    query = f"SELECT * FROM users WHERE id = {user_id}"
+    cursor.execute(query)
+    return cursor.fetchone()
     # end
"""


def _exp(file="app/users.py", lo=11, hi=12, category="security", sev="error"):
    return Expected(file=file, line_range=(lo, hi), category=category, min_severity=sev)


def _finding(
    file="app/users.py", line=11, category="security", severity="critical", **extra
):
    return {
        "file_path": file,
        "line_number": line,
        "category": category,
        "severity": severity,
        "body": "Query built with an f-string.",
        **extra,
    }


class TestMatchCase:
    def test_exact_match(self):
        result = match_case([_exp()], [_finding()])
        assert len(result.matched) == 1
        assert result.missed == []
        assert result.extra == []
        assert result.partial == []

    def test_line_at_range_boundaries_matches(self):
        for line in (11, 12):
            result = match_case([_exp()], [_finding(line=line)])
            assert len(result.matched) == 1, line

    def test_line_outside_range_is_miss_plus_extra(self):
        result = match_case([_exp()], [_finding(line=30)])
        assert result.matched == []
        assert len(result.missed) == 1
        assert len(result.extra) == 1

    def test_wrong_file_is_miss_plus_extra(self):
        result = match_case([_exp()], [_finding(file="app/other.py")])
        assert result.matched == []
        assert len(result.missed) == 1
        assert len(result.extra) == 1

    def test_wrong_category_is_partial(self):
        result = match_case([_exp()], [_finding(category="quality")])
        assert result.matched == []
        assert len(result.partial) == 1
        assert result.missed == []
        assert result.extra == []

    def test_severity_below_minimum_is_partial(self):
        result = match_case([_exp(sev="error")], [_finding(severity="warning")])
        assert result.matched == []
        assert len(result.partial) == 1

    def test_severity_above_minimum_matches(self):
        result = match_case([_exp(sev="warning")], [_finding(severity="critical")])
        assert len(result.matched) == 1

    def test_no_findings_is_miss(self):
        result = match_case([_exp()], [])
        assert len(result.missed) == 1
        assert result.matched == [] and result.extra == []

    def test_clean_case_with_no_findings_is_empty(self):
        result = match_case([], [])
        assert (result.matched, result.partial, result.missed, result.extra) == (
            [],
            [],
            [],
            [],
        )

    def test_clean_case_with_finding_is_extra(self):
        result = match_case([], [_finding()])
        assert len(result.extra) == 1

    def test_one_finding_cannot_match_two_expected(self):
        expected = [_exp(lo=11, hi=11), _exp(lo=11, hi=12)]
        result = match_case(expected, [_finding(line=11)])
        assert len(result.matched) == 1
        assert len(result.missed) == 1

    def test_duplicate_findings_count_one_match_and_one_extra(self):
        result = match_case([_exp()], [_finding(line=11), _finding(line=12)])
        assert len(result.matched) == 1
        assert len(result.extra) == 1

    def test_full_match_preferred_over_earlier_partial(self):
        findings = [_finding(category="quality"), _finding(category="security")]
        result = match_case([_exp()], findings)
        assert len(result.matched) == 1
        assert result.matched[0][1]["category"] == "security"
        # The quality finding is unrelated to any other expected item.
        assert len(result.extra) == 1

    def test_path_prefixes_are_normalised(self):
        for path in ("b/app/users.py", "/app/users.py", "./app/users.py"):
            result = match_case([_exp()], [_finding(file=path)])
            assert len(result.matched) == 1, path

    def test_category_aliases_match(self):
        result = match_case(
            [_exp(category="tests", sev="info")],
            [_finding(category="Test Coverage", severity="info")],
        )
        assert len(result.matched) == 1

    def test_expected_category_list_accepts_any(self):
        exp = _exp(category=["security", "quality"])
        result = match_case([exp], [_finding(category="quality")])
        assert len(result.matched) == 1

    def test_extra_response_fields_are_tolerated(self):
        finding = _finding(suggested_fix="use params", confidence=0.9, rule="x")
        result = match_case([_exp()], [finding])
        assert len(result.matched) == 1

    def test_string_line_number_is_accepted(self):
        result = match_case([_exp()], [_finding(line="12")])
        assert len(result.matched) == 1

    def test_enum_severity_is_accepted(self):
        from models.review import Severity

        result = match_case([_exp()], [_finding(severity=Severity.ERROR)])
        assert len(result.matched) == 1

    def test_garbage_line_number_never_matches(self):
        result = match_case([_exp()], [_finding(line="n/a")])
        assert result.matched == []
        assert len(result.extra) == 1


class TestNormalisers:
    def test_normalize_path(self):
        assert normalize_path("a/src/x.py") == "src/x.py"
        assert normalize_path(" b/src/x.py ") == "src/x.py"
        assert normalize_path("src\\x.py") == "src/x.py"
        assert normalize_path(None) == ""

    def test_normalize_category(self):
        assert normalize_category("SECURITY") == "security"
        assert normalize_category("testing") == "tests"
        assert normalize_category("performance") == "quality"
        assert normalize_category("something-new") == "something-new"


class TestNewSideLines:
    def test_added_and_context_lines_are_valid(self):
        lines = new_side_lines(DIFF)
        assert lines == {"app/users.py": {10, 11, 12, 13, 14}}

    def test_removed_lines_do_not_advance_new_side(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,2 @@\n keep\n-gone\n-gone2\n+new\n"
        assert new_side_lines(diff) == {"x.py": {1, 2}}

    def test_new_file_and_deleted_file(self):
        diff = (
            "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+a\n+b\n"
            "--- a/old.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-a\n"
        )
        assert new_side_lines(diff) == {"new.py": {1, 2}}

    def test_strict_mode_rejects_wrong_hunk_counts(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,3 @@\n+a\n"
        with pytest.raises(ValueError):
            new_side_lines(diff, strict=True)


class TestAggregate:
    def _case(self, expected, findings, diff=DIFF):
        return {"diff": diff, "expected": expected, "findings": findings}

    def test_metrics_over_cases(self):
        cases = [
            # 1 match, 1 extra on a line outside the diff
            self._case([_exp()], [_finding(), _finding(line=99)]),
            # 1 miss
            self._case([_exp()], []),
            # clean, no findings
            self._case([], []),
            # clean, one finding -> false positive case
            self._case([], [_finding(line=13, category="quality")]),
        ]
        m = aggregate(cases)
        assert m["cases"] == 4
        assert m["clean_cases"] == 2
        assert m["expected_total"] == 2
        assert m["findings_total"] == 3
        assert m["matched"] == 1
        assert m["precision"] == pytest.approx(1 / 3)
        assert m["recall"] == pytest.approx(1 / 2)
        assert m["clean_false_positive_rate"] == pytest.approx(1 / 2)
        assert m["clean_findings_total"] == 1
        # line 99 is outside the diff; lines 11 and 13 are inside
        assert m["valid_line_rate"] == pytest.approx(2 / 3)

    def test_undefined_ratios_are_none(self):
        m = aggregate([self._case([], [])])
        assert m["precision"] is None
        assert m["recall"] is None
        assert m["valid_line_rate"] is None
        assert m["clean_false_positive_rate"] == 0.0


# A new file with one 20-line hunk, and a second file, for near-match tests.
BIG_DIFF = (
    "--- /dev/null\n+++ b/svc/big.py\n@@ -0,0 +1,20 @@\n"
    + "".join(f"+line{i}\n" for i in range(1, 21))
    + "--- /dev/null\n+++ b/svc/other.py\n@@ -0,0 +1,2 @@\n+a\n+b\n"
)
BIG_HUNKS = diff_hunks(BIG_DIFF)


def _big_exp(lo=2, hi=2, **kw):
    return _exp(file="svc/big.py", lo=lo, hi=hi, **kw)


class TestNearMatches:
    def test_within_three_lines_is_near_not_matched(self):
        result = match_case([_big_exp(lo=10, hi=10)], [_finding("svc/big.py", 13)])
        assert result.matched == []
        assert len(result.near) == 1
        assert result.extra == [] and result.missed == []

    def test_same_hunk_beyond_three_lines_is_near(self):
        result = match_case([_big_exp()], [_finding("svc/big.py", 19)], BIG_HUNKS)
        assert len(result.near) == 1

    def test_same_hunk_rule_needs_hunk_info(self):
        result = match_case([_big_exp()], [_finding("svc/big.py", 19)])
        assert result.near == []
        assert len(result.missed) == 1 and len(result.extra) == 1

    def test_near_needs_right_category(self):
        result = match_case(
            [_big_exp()], [_finding("svc/big.py", 3, category="quality")], BIG_HUNKS
        )
        assert result.near == [] and result.partial == []
        assert len(result.missed) == 1 and len(result.extra) == 1

    def test_near_needs_same_file(self):
        result = match_case([_big_exp()], [_finding("svc/other.py", 2)], BIG_HUNKS)
        assert result.near == []
        assert len(result.extra) == 1

    def test_file_level_comment_is_never_near(self):
        result = match_case(
            [_big_exp(lo=1, hi=1)], [_finding("svc/big.py", 0)], BIG_HUNKS
        )
        assert result.near == []
        assert len(result.extra) == 1

    def test_exact_match_preferred_over_near(self):
        findings = [_finding("svc/big.py", 4), _finding("svc/big.py", 2)]
        result = match_case([_big_exp()], findings, BIG_HUNKS)
        assert len(result.matched) == 1
        assert result.matched[0][1]["line_number"] == 2
        assert result.near == []


class TestAlternativeLocations:
    def test_finding_at_alternative_location_matches(self):
        exp = Expected(
            file="app/users.py",
            line_range=(11, 12),
            category="tests",
            min_severity="info",
            alternatives=(("tests/test_users.py", (3, 6)),),
        )
        finding = _finding("tests/test_users.py", 5, category="tests", severity="info")
        result = match_case([exp], [finding])
        assert len(result.matched) == 1


class TestCategoryFolding:
    @pytest.mark.parametrize(
        "label, folded",
        [
            ("SQL Injection", "security"),
            ("Path Traversal", "security"),
            ("Cross\u2011Site Scripting (XSS)", "security"),
            ("xss", "security"),
            ("Hardcoded Secret", "security"),
            ("hard-coded credentials", "security"),
            ("Unsafe deserialization", "security"),
            ("Authorization", "security"),
            ("Security - Input Validation / SSRF", "security"),
            ("test-coverage", "tests"),
            ("Insufficient test coverage", "tests"),
            ("InsufficientCoverage", "tests"),
            ("test patterns", "tests"),
            ("error\u2011handling", "quality"),
            ("Error handling", "quality"),
            ("Exception handling", "quality"),
            ("business\u2011logic", "quality"),
            ("Correctness/Async Handling", "quality"),
            ("code_quality", "quality"),
            ("best_practice", "quality"),
        ],
    )
    def test_common_labels_fold(self, label, folded):
        assert normalize_category(label) == folded

    def test_unrelated_labels_are_not_folded(self):
        assert normalize_category("Input validation") == "input validation"
        assert normalize_category("MissingImport") == "missingimport"


class TestErroredCasesAndDedup:
    def _case(self, expected, findings, error=None, diff=DIFF, raw=None):
        case = {"diff": diff, "expected": expected, "findings": findings}
        if error:
            case["error"] = error
        if raw is not None:
            case["raw_findings"] = raw
        return case

    def test_errored_defect_case_counts_as_missed(self):
        m = aggregate(
            [
                self._case([_exp()], [_finding()]),
                self._case([_exp()], [], error="ParseFailure: 1"),
            ]
        )
        assert m["cases_scored"] == 1 and m["cases_errored"] == 1
        assert m["expected_total"] == 2
        assert m["recall"] == pytest.approx(1 / 2)

    def test_errored_clean_case_counts_as_false_positive_case(self):
        m = aggregate([self._case([], []), self._case([], [], error="CassetteMiss: x")])
        assert m["clean_cases"] == 2
        assert m["clean_false_positive_rate"] == pytest.approx(1 / 2)

    def test_findings_of_errored_case_are_not_scored(self):
        m = aggregate([self._case([], [_finding()], error="boom")])
        assert m["findings_total"] == 0
        assert m["precision"] is None

    def test_duplicates_collapse_for_dedup_precision(self):
        dupes = [_finding(), _finding(), _finding(category="SQL injection")]
        m = aggregate([self._case([_exp()], dupes)])
        assert m["precision"] == pytest.approx(1 / 3)
        assert m["unique_findings_total"] == 1
        assert m["precision_dedup"] == pytest.approx(1.0)

    def test_tolerant_metrics_count_near_matches(self):
        m = aggregate([self._case([_exp(lo=11, hi=11)], [_finding(line=13)])])
        assert m["recall"] == 0.0
        assert m["recall_tolerant"] == pytest.approx(1.0)
        assert m["precision_tolerant"] == pytest.approx(1.0)

    def test_valid_line_rate_uses_raw_findings(self):
        # Posted finding was moved to line 0 (file-level); the agent's raw
        # line 99 is what the valid-line rate judges.
        m = aggregate([self._case([], [_finding(line=0)], raw=[_finding(line=99)])])
        assert m["raw_findings_total"] == 1
        assert m["valid_line_rate"] == 0.0
