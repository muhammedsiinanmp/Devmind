"""
Score review-agent findings against labeled expected findings.

A finding fully matches an expected item when it names the same file, its
line falls inside the expected line range (new-file line numbers), its
category matches and its severity is at least the expected minimum.

Classification per case (each list is disjoint):
- matched: (expected, finding) pairs that fully match
- partial: (expected, finding) pairs with the right file and line but the
  wrong category or a severity below the minimum; not counted as matches
- missed:  expected items with no matching or partial finding
- extra:   findings that matched nothing

Scores are only as current as the findings fed in. In replay mode those come
from cassettes keyed by prompt hash, so a replay re-scores old model output
and cannot measure the effect of a prompt change: a changed prompt has no
recorded response and the case is reported as stale. Measuring a prompt or
model change needs a live run (``make eval-record``).
"""

import re
from dataclasses import dataclass, field
from typing import Any

SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}

# The agent runs three analyzers (security, quality, tests). Models sometimes
# return a more specific label; fold the common ones into those three.
CATEGORY_ALIASES = {
    "security": "security",
    "vulnerability": "security",
    "quality": "quality",
    "code quality": "quality",
    "code_quality": "quality",
    "bug": "quality",
    "correctness": "quality",
    "performance": "quality",
    "error handling": "quality",
    "error_handling": "quality",
    "maintainability": "quality",
    "readability": "quality",
    "tests": "tests",
    "test": "tests",
    "testing": "tests",
    "test coverage": "tests",
    "test_coverage": "tests",
}

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Expected:
    file: str
    line_range: tuple[int, int]
    category: str | list[str]
    min_severity: str = "info"

    @property
    def categories(self) -> set[str]:
        raw = [self.category] if isinstance(self.category, str) else self.category
        return {normalize_category(c) for c in raw}


@dataclass
class CaseMatch:
    matched: list[tuple[Expected, dict]] = field(default_factory=list)
    partial: list[tuple[Expected, dict]] = field(default_factory=list)
    missed: list[Expected] = field(default_factory=list)
    extra: list[dict] = field(default_factory=list)


def normalize_path(path: Any) -> str:
    if not path:
        return ""
    p = str(path).strip().replace("\\", "/")
    for prefix in ("a/", "b/", "./", "/"):
        if p.startswith(prefix):
            p = p[len(prefix) :]
            break
    return p


def normalize_category(category: Any) -> str:
    c = str(category or "").strip().lower()
    return CATEGORY_ALIASES.get(c, c)


def _line(finding: dict) -> int | None:
    try:
        return int(finding.get("line_number"))
    except (TypeError, ValueError):
        return None


def _location_ok(exp: Expected, finding: dict) -> bool:
    line = _line(finding)
    if line is None:
        return False
    lo, hi = exp.line_range
    return normalize_path(finding.get("file_path")) == normalize_path(exp.file) and (
        lo <= line <= hi
    )


def _full_match(exp: Expected, finding: dict) -> bool:
    if not _location_ok(exp, finding):
        return False
    if normalize_category(finding.get("category")) not in exp.categories:
        return False
    raw = finding.get("severity", "")
    severity = str(getattr(raw, "value", raw)).strip().lower()
    return SEVERITY_RANK.get(severity, -1) >= SEVERITY_RANK[exp.min_severity]


def match_case(expected: list[Expected], findings: list[dict]) -> CaseMatch:
    """Greedy one-to-one matching; full matches are assigned before partials."""
    result = CaseMatch()
    used: set[int] = set()
    unmatched: list[Expected] = []

    for exp in expected:
        idx = next(
            (
                i
                for i, f in enumerate(findings)
                if i not in used and _full_match(exp, f)
            ),
            None,
        )
        if idx is None:
            unmatched.append(exp)
        else:
            used.add(idx)
            result.matched.append((exp, findings[idx]))

    for exp in unmatched:
        idx = next(
            (
                i
                for i, f in enumerate(findings)
                if i not in used and _location_ok(exp, f)
            ),
            None,
        )
        if idx is None:
            result.missed.append(exp)
        else:
            used.add(idx)
            result.partial.append((exp, findings[idx]))

    result.extra = [f for i, f in enumerate(findings) if i not in used]
    return result


def new_side_lines(diff_text: str, strict: bool = False) -> dict[str, set[int]]:
    """Map each file in a unified diff to the new-file line numbers it shows.

    Added and context lines count; removed lines don't. With ``strict`` the
    hunk header counts must agree with the hunk body (used to validate the
    hand-written eval cases).
    """
    lines_by_file: dict[str, set[int]] = {}
    current: str | None = None
    new_line = 0
    remaining_old = remaining_new = 0

    def _check_hunk_closed() -> None:
        if strict and (remaining_old or remaining_new):
            raise ValueError(
                f"hunk in {current!r} has {remaining_old} old / "
                f"{remaining_new} new lines unaccounted for"
            )

    for raw in diff_text.splitlines():
        in_hunk = remaining_old > 0 or remaining_new > 0
        if raw.startswith("+++ ") and not in_hunk:
            remaining_old = remaining_new = 0
            target = raw[4:].strip()
            current = None if target == "/dev/null" else normalize_path(target)
            if current is not None:
                lines_by_file.setdefault(current, set())
            continue
        if raw.startswith("--- ") and not in_hunk:
            continue
        hunk = _HUNK_RE.match(raw)
        if hunk:
            _check_hunk_closed()
            remaining_old = int(hunk.group(2) if hunk.group(2) is not None else 1)
            new_line = int(hunk.group(3))
            remaining_new = int(hunk.group(4) if hunk.group(4) is not None else 1)
            continue
        if not in_hunk:
            continue  # file headers, "diff --git", "index", etc.
        if raw.startswith("\\"):
            continue  # "\ No newline at end of file"
        tag = raw[:1]
        if tag == "-":
            remaining_old -= 1
        elif tag == "+":
            if current is not None:
                lines_by_file[current].add(new_line)
            new_line += 1
            remaining_new -= 1
        else:  # context line (" " or an empty line from a stripped editor)
            if current is not None:
                lines_by_file[current].add(new_line)
            new_line += 1
            remaining_old -= 1
            remaining_new -= 1
        if strict and (remaining_old < 0 or remaining_new < 0):
            raise ValueError(f"hunk in {current!r} is longer than its header says")

    _check_hunk_closed()
    return lines_by_file


def is_valid_line(finding: dict, lines_by_file: dict[str, set[int]]) -> bool:
    line = _line(finding)
    path = normalize_path(finding.get("file_path"))
    return line is not None and line in lines_by_file.get(path, set())


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def aggregate(cases: list[dict]) -> dict[str, Any]:
    """Compute run-level metrics.

    Each item needs ``diff`` (str), ``expected`` (list[Expected]) and
    ``findings`` (list[dict]).
    """
    totals = {
        "cases": len(cases),
        "clean_cases": 0,
        "clean_cases_with_findings": 0,
        "clean_findings_total": 0,
        "expected_total": 0,
        "findings_total": 0,
        "matched": 0,
        "partial": 0,
        "missed": 0,
        "extra": 0,
        "valid_line_findings": 0,
    }
    for case in cases:
        findings = case["findings"]
        res = match_case(case["expected"], findings)
        lines = new_side_lines(case["diff"])
        totals["expected_total"] += len(case["expected"])
        totals["findings_total"] += len(findings)
        totals["matched"] += len(res.matched)
        totals["partial"] += len(res.partial)
        totals["missed"] += len(res.missed)
        totals["extra"] += len(res.extra)
        totals["valid_line_findings"] += sum(is_valid_line(f, lines) for f in findings)
        if not case["expected"]:
            totals["clean_cases"] += 1
            totals["clean_findings_total"] += len(findings)
            if findings:
                totals["clean_cases_with_findings"] += 1

    return {
        **totals,
        "precision": _ratio(totals["matched"], totals["findings_total"]),
        "recall": _ratio(totals["matched"], totals["expected_total"]),
        "clean_false_positive_rate": _ratio(
            totals["clean_cases_with_findings"], totals["clean_cases"]
        ),
        "valid_line_rate": _ratio(
            totals["valid_line_findings"], totals["findings_total"]
        ),
    }
