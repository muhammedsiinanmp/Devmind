"""Load and validate eval cases from evals/cases/*.yaml."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from evals.matcher import SEVERITY_RANK, Expected

CASES_DIR = Path(__file__).parent / "cases"
CATEGORIES = {"security", "quality", "tests"}


@dataclass(frozen=True)
class Case:
    id: str
    description: str
    diff: str
    expected: list[Expected]

    @property
    def digest(self) -> str:
        """Hash of the diff; cassettes recorded for an older diff are stale."""
        return hashlib.sha256(self.diff.encode()).hexdigest()


def _parse_range(case_id: str, raw: object) -> tuple[int, int]:
    try:
        lo, hi = (int(n) for n in raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{case_id}: malformed line_range {raw!r}") from exc
    if lo > hi or lo < 1:
        raise ValueError(f"{case_id}: bad line_range {[lo, hi]}")
    return lo, hi


def _parse_expected(case_id: str, item: dict) -> Expected:
    try:
        lo, hi = _parse_range(case_id, item["line_range"])
        category = item["category"]
        min_severity = str(item.get("min_severity", "info")).lower()
        file = str(item["file"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{case_id}: malformed expected item {item!r}") from exc
    cats = [category] if isinstance(category, str) else list(category)
    if not cats or not set(cats) <= CATEGORIES:
        raise ValueError(f"{case_id}: category must be one of {sorted(CATEGORIES)}")
    if min_severity not in SEVERITY_RANK:
        raise ValueError(f"{case_id}: unknown min_severity {min_severity!r}")
    alternatives = []
    for alt in item.get("alternatives") or []:
        if not isinstance(alt, dict) or "file" not in alt:
            raise ValueError(f"{case_id}: malformed alternative {alt!r}")
        alternatives.append(
            (str(alt["file"]), _parse_range(case_id, alt.get("line_range")))
        )
    return Expected(
        file=file,
        line_range=(lo, hi),
        category=category if isinstance(category, str) else cats,
        min_severity=min_severity,
        alternatives=tuple(alternatives),
    )


def load_case(path: Path) -> Case:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: not a mapping")
    case_id = str(data.get("id") or path.stem)
    diff = data.get("diff")
    if not isinstance(diff, str) or not diff.strip():
        raise ValueError(f"{case_id}: missing diff")
    expected_raw = data.get("expected")
    if not isinstance(expected_raw, list):
        raise ValueError(f"{case_id}: 'expected' must be a list (use [] for clean)")
    return Case(
        id=case_id,
        description=str(data.get("description", "")),
        diff=diff,
        expected=[_parse_expected(case_id, item) for item in expected_raw],
    )


def load_cases(directory: Path = CASES_DIR, only: set[str] | None = None) -> list:
    cases = [load_case(p) for p in sorted(directory.glob("*.yaml"))]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    if only:
        unknown = only - set(ids)
        if unknown:
            raise ValueError(f"unknown case ids: {sorted(unknown)}")
        cases = [c for c in cases if c.id in only]
    return cases
