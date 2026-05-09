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
from services.github_client import (
    GitHubClient,
    GitHubClientError,
    get_language,
    should_skip_path,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scan", tags=["scan"])

settings = get_settings()

SCAN_PROGRESS: dict[int, dict[str, Any]] = {}


class ScanRequest(BaseModel):
    repo_full_name: str
    repo_url: str
    branch: str = "main"
    github_token: str | None = None


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


async def scan_repository(
    scan_id: int,
    repo_full_name: str,
    repo_url: str,
    branch: str,
    github_token: str | None = None,
) -> ScanResult:
    """Scan a repository for issues using real GitHub API."""
    start_time = time.perf_counter()

    SCAN_PROGRESS[scan_id] = {
        "status": "scanning",
        "files_scanned": 0,
        "total_files": 0,
        "progress": 0,
        "issues": [],
        "health_score": 100,
    }

    try:
        # Parse owner/repo from full_name
        parts = repo_full_name.split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid repo_full_name: {repo_full_name}")
        owner, repo = parts

        # Initialize GitHub client
        client = GitHubClient(token=github_token)

        # Get default branch if not specified
        if not branch:
            branch = await client.get_default_branch(owner, repo)

        # Get repository tree
        logger.info(f"Fetching tree for {owner}/{repo} branch {branch}")
        tree = await client.get_repository_tree(
            owner, repo, branch=branch, recursive=True
        )

        # Filter to only code files
        code_files = []
        for item in tree:
            if item.get("type") == "blob":
                path = item.get("path", "")
                if not should_skip_path(path):
                    code_files.append(path)

        total_files = len(code_files)
        SCAN_PROGRESS[scan_id]["total_files"] = total_files

        logger.info(f"Found {total_files} files to scan")

        # Process files in batches
        batch_size = 50
        all_issues = []
        files_scanned = 0

        for i in range(0, total_files, batch_size):
            batch_paths = code_files[i : i + batch_size]

            # Fetch file contents for this batch
            batch_files = []
            for path in batch_paths:
                try:
                    content = await client.get_file_content(
                        owner, repo, path, ref=branch
                    )
                    language = get_language(path)
                    batch_files.append((path, content, language))
                except GitHubClientError as e:
                    logger.warning(f"Failed to fetch {path}: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"Error fetching {path}: {e}")
                    continue

            # Scan each file
            for path, content, language in batch_files:
                # Scan for secrets
                issues = _scan_file_for_secrets(content)
                for issue in issues:
                    issue["file_path"] = path
                    issue["language"] = language
                all_issues.extend(issues)

                # Scan for security issues
                issues = _scan_file_for_security(content)
                for issue in issues:
                    issue["file_path"] = path
                    issue["language"] = language
                all_issues.extend(issues)

                # Scan for quality issues
                issues = _scan_file_for_quality(content, language)
                for issue in issues:
                    issue["file_path"] = path
                    issue["language"] = language
                all_issues.extend(issues)

                files_scanned += 1
                SCAN_PROGRESS[scan_id]["files_scanned"] = files_scanned
                SCAN_PROGRESS[scan_id]["progress"] = int(
                    (files_scanned / total_files) * 100
                )

            # Rate limiting - be nice to GitHub API
            await asyncio.sleep(0.5)

        await client.close()

    except GitHubClientError as e:
        logger.error(f"GitHub client error: {e}")
        SCAN_PROGRESS[scan_id]["status"] = "failed"
        return ScanResult(
            scan_id=scan_id,
            status="failed",
            files_scanned=0,
            total_files=0,
            issues=[],
            health_score=0,
        )
    except Exception as e:
        logger.error(f"Scan error: {e}")
        SCAN_PROGRESS[scan_id]["status"] = "failed"
        return ScanResult(
            scan_id=scan_id,
            status="failed",
            files_scanned=0,
            total_files=0,
            issues=[],
            health_score=0,
        )

    # Calculate health score
    critical_count = sum(1 for i in all_issues if i.get("severity") == "critical")
    error_count = sum(1 for i in all_issues if i.get("severity") == "error")
    warning_count = sum(1 for i in all_issues if i.get("severity") == "warning")

    health_score = max(
        0,
        100 - (critical_count * 10) - (error_count * 5) - (warning_count * 1),
    )

    end_time = time.perf_counter()
    scan_duration_ms = int((end_time - start_time) * 1000)

    SCAN_PROGRESS[scan_id]["status"] = "completed"
    SCAN_PROGRESS[scan_id]["progress"] = 100
    SCAN_PROGRESS[scan_id]["issues"] = all_issues
    SCAN_PROGRESS[scan_id]["health_score"] = health_score
    SCAN_PROGRESS[scan_id]["scan_duration_ms"] = scan_duration_ms

    logger.info(
        f"Scan completed: {files_scanned} files, {len(all_issues)} issues, health={health_score}"
    )

    return ScanResult(
        scan_id=scan_id,
        status="completed",
        files_scanned=files_scanned,
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

    asyncio.create_task(
        scan_repository(
            scan_id=scan_id,
            repo_full_name=request.repo_full_name,
            repo_url=request.repo_url,
            branch=request.branch,
            github_token=request.github_token,
        )
    )

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
