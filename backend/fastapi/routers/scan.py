"""
Full repository scan endpoints.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scan", tags=["scan"])

settings = get_settings()

SCAN_PROGRESS: dict[int, dict[str, Any]] = {}


class ScanRequest(BaseModel):
    repo_full_name: str
    repo_url: str
    branch: str = "main"


class ScanStatusResponse(BaseModel):
    scan_id: int
    status: str
    progress: int
    files_scanned: int
    total_files: int


class ScanReportResponse(BaseModel):
    scan_id: int
    status: str
    health_score: int
    issues_by_category: dict[str, int]
    total_issues: int
    files_scanned: int
    scan_duration_ms: int


class ScanResponse(BaseModel):
    scan_id: int
    status: str
    message: str


@dataclass
class ScanResult:
    """Result from a repository scan."""

    scan_id: int
    status: str
    files_scanned: int
    total_files: int
    issues: list[dict[str, Any]] = field(default_factory=list)
    health_score: int = 100
    scan_duration_ms: int = 0


def _detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".kt": "kotlin",
        ".rb": "ruby",
        ".php": "php",
        ".cs": "csharp",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".swift": "swift",
        ".scala": "scala",
        ".vue": "vue",
        ".svelte": "svelte",
    }
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    return "unknown"


def _scan_file_for_secrets(content: str) -> list[dict[str, Any]]:
    """Scan a file for hardcoded secrets using regex patterns."""
    issues = []

    patterns = [
        (r"sk-[a-zA-Z0-9]{20,}", "Hardcoded OpenAI API key"),
        (r"AIza[0-9A-Za-z_-]{35}", "Hardcoded Google API key"),
        (r"ghp_[a-zA-Z0-9]{36}", "Hardcoded GitHub token"),
        (r"AKIA[0-9A-Z]{16}", "Hardcoded AWS access key"),
        (r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----", "Private key in code"),
    ]

    for pattern, description in patterns:
        import re

        matches = re.finditer(pattern, content)
        for match in matches:
            issues.append(
                {
                    "type": "secret",
                    "severity": "critical",
                    "file_path": "",
                    "line_number": content[: match.start()].count("\n") + 1,
                    "body": f"{description} detected",
                }
            )

    return issues


def _scan_file_for_security(content: str) -> list[dict[str, Any]]:
    """Scan a file for security issues."""
    issues = []
    lines = content.split("\n")

    for i, line in enumerate(lines, 1):
        if "eval(" in line or "exec(" in line:
            issues.append(
                {
                    "type": "security",
                    "severity": "critical",
                    "file_path": "",
                    "line_number": i,
                    "body": "Dangerous function usage: eval()/exec()",
                }
            )

        if "os.system(" in line or "subprocess.call(" in line:
            issues.append(
                {
                    "type": "security",
                    "severity": "error",
                    "file_path": "",
                    "line_number": i,
                    "body": "Potential command injection: os.system/subprocess",
                }
            )

        if "pickle.load" in line or "yaml.load" in line:
            issues.append(
                {
                    "type": "security",
                    "severity": "warning",
                    "file_path": "",
                    "line_number": i,
                    "body": "Unsafe deserialization: pickle/yaml.load",
                }
            )

    return issues


def _scan_file_for_quality(content: str, language: str) -> list[dict[str, Any]]:
    """Scan a file for code quality issues."""
    issues = []
    lines = content.split("\n")

    if language != "python":
        return issues

    for i, line in enumerate(lines, 1):
        if len(line) > 120:
            issues.append(
                {
                    "type": "quality",
                    "severity": "info",
                    "file_path": "",
                    "line_number": i,
                    "body": f"Line too long ({len(line)} > 120 chars)",
                }
            )

    function_bodies = []
    in_function = False
    function_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            if in_function and function_bodies:
                function_bodies[-1]["end"] = i - 1
            in_function = True
            function_start = i
            function_bodies.append({"start": function_start, "lines": 0})
        if in_function:
            function_bodies[-1]["lines"] += 1

    if in_function and function_bodies:
        function_bodies[-1]["end"] = len(lines)

    for func in function_bodies:
        if func["lines"] > 50:
            issues.append(
                {
                    "type": "quality",
                    "severity": "warning",
                    "file_path": "",
                    "line_number": func["start"] + 1,
                    "body": f"Function too long ({func['lines']} lines > 50)",
                }
            )

    for i, line in enumerate(lines, 1):
        if "TODO" in line or "FIXME" in line or "HACK" in line:
            issues.append(
                {
                    "type": "quality",
                    "severity": "info",
                    "file_path": "",
                    "line_number": i,
                    "body": f"Comment marker: {line.strip()[:50]}",
                }
            )

    return issues


def _scan_files_batch(
    files: list[tuple[str, str]], scan_id: int
) -> tuple[list[dict[str, Any]], int]:
    """Scan a batch of files and return issues found."""
    all_issues = []
    for file_path, content in files:
        language = _detect_language(file_path)

        issues = _scan_file_for_secrets(content)
        issues.extend(_scan_file_for_security(content))
        issues.extend(_scan_file_for_quality(content, language))

        for issue in issues:
            issue["file_path"] = file_path

        all_issues.extend(issues)

        SCAN_PROGRESS[scan_id]["files_scanned"] += 1

    return all_issues


async def scan_repository(scan_id: int, repo_url: str, branch: str) -> ScanResult:
    """Scan a repository for issues."""
    start_time = time.perf_counter()

    SCAN_PROGRESS[scan_id] = {
        "status": "scanning",
        "files_scanned": 0,
        "total_files": 100,
        "progress": 0,
    }

    mock_files = [
        (
            "src/main.py",
            'import os\nimport pickle\n\ndef unsafe():\n    eval("os.system(ls)")',
        ),
        ("src/utils.py", 'API_KEY = "sk-1234567890abcdefghijklmnop"'),
        ("src/config.py", "TODO: Fix this later"),
        ("src/long.py", "\n".join([f"x = {i}" for i in range(60)])),
    ]

    batch_size = 50
    total_files = len(mock_files)

    all_issues = []

    for i in range(0, total_files, batch_size):
        batch = mock_files[i : i + batch_size]
        issues = _scan_files_batch(batch, scan_id)
        all_issues.extend(issues)

        SCAN_PROGRESS[scan_id]["files_scanned"] = min(i + batch_size, total_files)
        SCAN_PROGRESS[scan_id]["progress"] = int(
            (SCAN_PROGRESS[scan_id]["files_scanned"] / total_files) * 100
        )

        await asyncio.sleep(0.1)

    critical_count = sum(1 for i in all_issues if i["severity"] == "critical")
    error_count = sum(1 for i in all_issues if i["severity"] == "error")
    warning_count = sum(1 for i in all_issues if i["severity"] == "warning")

    health_score = max(
        0,
        100 - (critical_count * 10) - (error_count * 5) - (warning_count * 1),
    )

    end_time = time.perf_counter()
    scan_duration_ms = int((end_time - start_time) * 1000)

    SCAN_PROGRESS[scan_id]["status"] = "completed"
    SCAN_PROGRESS[scan_id]["progress"] = 100

    return ScanResult(
        scan_id=scan_id,
        status="completed",
        files_scanned=total_files,
        total_files=total_files,
        issues=all_issues,
        health_score=health_score,
        scan_duration_ms=scan_duration_ms,
    )


@router.post("/full", response_model=ScanResponse)
async def start_full_scan(request: ScanRequest):
    """Start a full repository scan."""
    scan_id = hash(f"{request.repo_full_name}{time.time()}") % 100000

    SCAN_PROGRESS[scan_id] = {
        "status": "queued",
        "files_scanned": 0,
        "total_files": 0,
        "progress": 0,
    }

    asyncio.create_task(scan_repository(scan_id, request.repo_url, request.branch))

    return ScanResponse(
        scan_id=scan_id,
        status="queued",
        message=f"Scan started for {request.repo_full_name}",
    )


@router.get("/status/{scan_id}", response_model=ScanStatusResponse)
async def get_scan_status(scan_id: int):
    """Get the status of a scan."""
    if scan_id not in SCAN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan {scan_id} not found",
        )

    progress = SCAN_PROGRESS[scan_id]

    return ScanStatusResponse(
        scan_id=scan_id,
        status=progress["status"],
        progress=progress["progress"],
        files_scanned=progress["files_scanned"],
        total_files=progress.get("total_files", 0),
    )


@router.get("/report/{scan_id}", response_model=ScanReportResponse)
async def get_scan_report(scan_id: int):
    """Get the detailed report of a completed scan."""
    if scan_id not in SCAN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan {scan_id} not found",
        )

    progress = SCAN_PROGRESS[scan_id]

    if progress["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scan {scan_id} is still {progress['status']}",
        )

    issues = progress.get("issues", [])
    issues_by_category = {}
    for issue in issues:
        cat = issue.get("type", "unknown")
        issues_by_category[cat] = issues_by_category.get(cat, 0) + 1

    return ScanReportResponse(
        scan_id=scan_id,
        status="completed",
        health_score=progress.get("health_score", 100),
        issues_by_category=issues_by_category,
        total_issues=len(issues),
        files_scanned=progress["files_scanned"],
        scan_duration_ms=progress.get("scan_duration_ms", 0),
    )
