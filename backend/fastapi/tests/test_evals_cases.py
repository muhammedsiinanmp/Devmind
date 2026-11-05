"""
Checks on the committed eval cases in evals/cases/, so a typo in a
hand-written diff or label can't silently skew the metrics.
"""

import re

import pytest

from evals.cases import CASES_DIR, load_case, load_cases
from evals.matcher import new_side_lines

CASES = load_cases(CASES_DIR)


def test_case_set_size():
    assert len(CASES) >= 24
    assert sum(1 for c in CASES if not c.expected) >= 8


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_diff_hunks_are_consistent(case):
    new_side_lines(case.diff, strict=True)


@pytest.mark.parametrize(
    "case", [c for c in CASES if c.expected], ids=[c.id for c in CASES if c.expected]
)
def test_expected_ranges_point_into_the_diff(case):
    lines = new_side_lines(case.diff, strict=True)
    for exp in case.expected:
        assert exp.file in lines, exp.file
        lo, hi = exp.line_range
        assert set(range(lo, hi + 1)) <= lines[exp.file], exp


def test_no_realistic_secret_formats_in_cases():
    # Cases use obviously fake values so nothing resembles a live credential.
    patterns = [
        r"AKIA[0-9A-Z]{16}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"sk-[A-Za-z0-9]{20,}",
    ]
    for path in CASES_DIR.glob("*.yaml"):
        text = path.read_text()
        for pat in patterns:
            assert not re.search(pat, text), (path.name, pat)


def test_loader_rejects_bad_category(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "id: bad\ndiff: |\n  x\nexpected:\n"
        "  - {file: a.py, line_range: [1, 1], category: style}\n"
    )
    with pytest.raises(ValueError):
        load_case(bad)


def test_loader_requires_explicit_expected_list(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: bad\ndiff: |\n  x\n")
    with pytest.raises(ValueError):
        load_case(bad)
