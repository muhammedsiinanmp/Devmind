"""
Score review-agent findings against labeled expected findings.

An expected item has one or more acceptable locations (a file and a range of
new-file line numbers), a category and a minimum severity.

Classification per case (each list is disjoint). Exact matches are assigned
first, then near matches, then partials, so each finding and each expected
item is used at most once:
- matched: right category, severity at least the minimum, and the finding's
  line is inside an expected location's range (exact location)
- near:    as matched, but the line is only within NEAR_DISTANCE lines of the
  range, or in the same diff hunk as it ("located near")
- partial: exact location, but the wrong category or a severity below the
  minimum; not counted as a match
- missed:  expected items with none of the above
- extra:   findings that matched nothing. Precision is measured against the
  labels, so a real issue nobody labeled, and a duplicate of a matched
  finding, both count as extra.

Scores are only as current as the findings fed in. In replay mode those come
from cassettes keyed by prompt hash, so a replay re-scores old model output
and cannot measure the effect of a prompt change: a changed prompt has no
recorded response and the case is reported as stale. Measuring a prompt or
model change needs a live run (``make eval-record``).
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}
NEAR_DISTANCE = 3

# The agent runs three analyzers (security, quality, tests), but models often
# return a more specific label ("SQL Injection", "test-coverage",
# "MissingImport"). A label is split into lowercase word tokens and folded by
# the first rule that applies: security words, then test words, then quality
# words. Anything else is kept as is and can't match a labeled category.
_SECURITY_TOKENS = {
    "security",
    "vulnerability",
    "injection",
    "sqli",
    "xss",
    "scripting",
    "traversal",
    "deserialization",
    "ssrf",
    "csrf",
    "secret",
    "secrets",
    "credential",
    "credentials",
    "password",
    "passwords",
    "authorization",
    "authentication",
    "auth",
    "crypto",
    "cryptography",
    "denial",
}
_TEST_TOKENS = {"coverage"}  # plus any token starting with "test"
_QUALITY_TOKENS = {
    "quality",
    "bug",
    "bugs",
    "correctness",
    "logic",
    "performance",
    "error",
    "errors",
    "exception",
    "exceptions",
    "maintainability",
    "readability",
    "robustness",
    "runtime",
    "concurrency",
    "async",
    "practice",
    "practices",
}

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True)
class Expected:
    file: str
    line_range: tuple[int, int]
    category: str | list[str]
    min_severity: str = "info"
    # Other acceptable (file, (first_line, last_line)) locations.
    alternatives: tuple[tuple[str, tuple[int, int]], ...] = ()

    @property
    def categories(self) -> set[str]:
        raw = [self.category] if isinstance(self.category, str) else self.category
        return {normalize_category(c) for c in raw}

    @property
    def locations(self) -> tuple[tuple[str, tuple[int, int]], ...]:
        return ((self.file, self.line_range), *self.alternatives)


@dataclass
class CaseMatch:
    matched: list[tuple[Expected, dict]] = field(default_factory=list)
    near: list[tuple[Expected, dict]] = field(default_factory=list)
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


def _tokens(label: str) -> list[str]:
    text = unicodedata.normalize("NFKC", label)
    text = _CAMEL_RE.sub(" ", text).lower()
    # Any non-alphanumeric character, including non-ASCII hyphens, splits.
    return [t for t in re.split(r"[^0-9a-z]+", text) if t]


def normalize_category(category: Any) -> str:
    raw = str(getattr(category, "value", category) or "").strip()
    tokens = _tokens(raw)
    if any(t in _SECURITY_TOKENS for t in tokens):
        return "security"
    if any(t.startswith("test") or t in _TEST_TOKENS for t in tokens):
        return "tests"
    if any(t in _QUALITY_TOKENS for t in tokens):
        return "quality"
    return raw.lower()


def _line(finding: dict) -> int | None:
    try:
        return int(finding.get("line_number"))
    except (TypeError, ValueError):
        return None


def _severity_ok(exp: Expected, finding: dict) -> bool:
    raw = finding.get("severity", "")
    severity = str(getattr(raw, "value", raw)).strip().lower()
    return SEVERITY_RANK.get(severity, -1) >= SEVERITY_RANK[exp.min_severity]


def _labels_ok(exp: Expected, finding: dict) -> bool:
    return normalize_category(
        finding.get("category")
    ) in exp.categories and _severity_ok(exp, finding)


def _location_ok(exp: Expected, finding: dict) -> bool:
    line = _line(finding)
    path = normalize_path(finding.get("file_path"))
    return line is not None and any(
        path == normalize_path(file) and lo <= line <= hi
        for file, (lo, hi) in exp.locations
    )


def _location_near(
    exp: Expected, finding: dict, hunks: dict[str, list[set[int]]]
) -> bool:
    line = _line(finding)
    if line is None or line < 1:
        return False
    path = normalize_path(finding.get("file_path"))
    for file, (lo, hi) in exp.locations:
        file = normalize_path(file)
        if path != file:
            continue
        if lo - NEAR_DISTANCE <= line <= hi + NEAR_DISTANCE:
            return True
        span = set(range(lo, hi + 1))
        if any(line in h and h & span for h in hunks.get(file, [])):
            return True
    return False


def match_case(
    expected: list[Expected],
    findings: list[dict],
    hunks: dict[str, list[set[int]]] | None = None,
) -> CaseMatch:
    """Greedy one-to-one matching: exact, then near, then partial.

    ``hunks`` (from diff_hunks) enables the same-hunk rule for near matches.
    """
    hunks = hunks or {}
    result = CaseMatch()
    used: set[int] = set()
    remaining = list(expected)

    def assign(rule, bucket: list) -> None:
        nonlocal remaining
        still = []
        for exp in remaining:
            idx = next(
                (i for i, f in enumerate(findings) if i not in used and rule(exp, f)),
                None,
            )
            if idx is None:
                still.append(exp)
            else:
                used.add(idx)
                bucket.append((exp, findings[idx]))
        remaining = still

    assign(lambda e, f: _location_ok(e, f) and _labels_ok(e, f), result.matched)
    assign(lambda e, f: _location_near(e, f, hunks) and _labels_ok(e, f), result.near)
    assign(_location_ok, result.partial)
    result.missed = remaining
    result.extra = [f for i, f in enumerate(findings) if i not in used]
    return result


def dedupe(findings: list[dict]) -> list[dict]:
    """Collapse findings with the same file, line and folded category."""
    seen: set[tuple] = set()
    unique = []
    for f in findings:
        key = (
            normalize_path(f.get("file_path")),
            _line(f),
            normalize_category(f.get("category")),
        )
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def diff_hunks(diff_text: str, strict: bool = False) -> dict[str, list[set[int]]]:
    """Map each file in a unified diff to the new-file lines of each hunk.

    Added and context lines count; removed lines don't. With ``strict`` the
    hunk header counts must agree with the hunk body (used to validate the
    hand-written eval cases).
    """
    hunks_by_file: dict[str, list[set[int]]] = {}
    current: str | None = None
    hunk: set[int] = set()
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
            target = raw[4:].strip()
            current = None if target == "/dev/null" else normalize_path(target)
            if current is not None:
                hunks_by_file.setdefault(current, [])
            continue
        if raw.startswith("--- ") and not in_hunk:
            continue
        header = _HUNK_RE.match(raw)
        if header:
            _check_hunk_closed()
            remaining_old = int(header.group(2) if header.group(2) is not None else 1)
            new_line = int(header.group(3))
            remaining_new = int(header.group(4) if header.group(4) is not None else 1)
            hunk = set()
            if current is not None:
                hunks_by_file[current].append(hunk)
            continue
        if not in_hunk:
            continue  # file headers, "diff --git", "index", etc.
        if raw.startswith("\\"):
            continue  # "\ No newline at end of file"
        tag = raw[:1]
        if tag == "-":
            remaining_old -= 1
        elif tag == "+":
            hunk.add(new_line)
            new_line += 1
            remaining_new -= 1
        else:  # context line (" " or an empty line from a stripped editor)
            hunk.add(new_line)
            new_line += 1
            remaining_old -= 1
            remaining_new -= 1
        if strict and (remaining_old < 0 or remaining_new < 0):
            raise ValueError(f"hunk in {current!r} is longer than its header says")

    _check_hunk_closed()
    return hunks_by_file


def new_side_lines(diff_text: str, strict: bool = False) -> dict[str, set[int]]:
    """Map each file in a unified diff to all new-file lines it shows."""
    return {
        file: set().union(*hunks) if hunks else set()
        for file, hunks in diff_hunks(diff_text, strict).items()
    }


def is_valid_line(finding: dict, lines_by_file: dict[str, set[int]]) -> bool:
    line = _line(finding)
    path = normalize_path(finding.get("file_path"))
    return line is not None and line in lines_by_file.get(path, set())


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def aggregate(cases: list[dict]) -> dict[str, Any]:
    """Compute run-level metrics.

    Each item needs ``diff`` (str), ``expected`` (list[Expected]) and
    ``findings`` (list[dict], what would be posted). Optional:
    ``raw_findings`` (agent output before anchoring; used for the valid-line
    rate, defaults to ``findings``) and ``error`` (str or None).

    An errored case is never dropped: its expected items count as missed, and
    an errored clean case counts as a clean-diff failure.
    """
    t = {
        "cases": len(cases),
        "cases_scored": 0,
        "cases_errored": 0,
        "clean_cases": 0,
        "clean_cases_with_findings": 0,
        "clean_cases_errored": 0,
        "clean_findings_total": 0,
        "expected_total": 0,
        "findings_total": 0,
        "unique_findings_total": 0,
        "matched": 0,
        "matched_dedup": 0,
        "near": 0,
        "partial": 0,
        "missed": 0,
        "extra": 0,
        "raw_findings_total": 0,
        "valid_line_findings": 0,
    }
    for case in cases:
        expected = case["expected"]
        clean = not expected
        t["expected_total"] += len(expected)
        t["clean_cases"] += clean
        if case.get("error"):
            t["cases_errored"] += 1
            t["missed"] += len(expected)
            t["clean_cases_errored"] += clean
            continue
        t["cases_scored"] += 1
        findings = case["findings"]
        raw = case.get("raw_findings", findings)
        hunks = diff_hunks(case["diff"])
        lines = {f: set().union(*h) if h else set() for f, h in hunks.items()}
        res = match_case(expected, findings, hunks)
        unique = dedupe(findings)
        t["findings_total"] += len(findings)
        t["unique_findings_total"] += len(unique)
        t["matched"] += len(res.matched)
        t["matched_dedup"] += len(match_case(expected, unique, hunks).matched)
        t["near"] += len(res.near)
        t["partial"] += len(res.partial)
        t["missed"] += len(res.missed)
        t["extra"] += len(res.extra)
        t["raw_findings_total"] += len(raw)
        t["valid_line_findings"] += sum(is_valid_line(f, lines) for f in raw)
        if clean:
            t["clean_findings_total"] += len(findings)
            t["clean_cases_with_findings"] += bool(findings)

    located = t["matched"] + t["near"]
    return {
        **t,
        "precision": _ratio(t["matched"], t["findings_total"]),
        "precision_dedup": _ratio(t["matched_dedup"], t["unique_findings_total"]),
        "precision_tolerant": _ratio(located, t["findings_total"]),
        "recall": _ratio(t["matched"], t["expected_total"]),
        "recall_tolerant": _ratio(located, t["expected_total"]),
        "clean_false_positive_rate": _ratio(
            t["clean_cases_with_findings"] + t["clean_cases_errored"],
            t["clean_cases"],
        ),
        "valid_line_rate": _ratio(t["valid_line_findings"], t["raw_findings_total"]),
    }
