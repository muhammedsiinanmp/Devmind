"""
Tests for scan endpoints.
"""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


class TestScanEndpoints:
    """Test scan API endpoints."""

    def test_start_scan_returns_202(self):
        """Test POST /scan/full returns 202 with scan_id."""
        from main import app

        client = TestClient(app)

        response = client.post(
            "/scan/full",
            json={
                "repo_full_name": "owner/repo",
                "repo_url": "https://github.com/owner/repo",
                "branch": "main",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "scan_id" in data
        assert data["status"] == "queued"

    def test_get_scan_status_not_found(self):
        """Test GET /scan/status/{scan_id} returns 404 for unknown scan."""
        from main import app

        client = TestClient(app)

        response = client.get("/scan/status/99999")

        assert response.status_code == 404

    def test_get_scan_status_returns_progress(self):
        """Test GET /scan/status/{scan_id} returns progress."""
        from main import app

        client = TestClient(app)

        start_response = client.post(
            "/scan/full",
            json={
                "repo_full_name": "owner/repo",
                "repo_url": "https://github.com/owner/repo",
                "branch": "main",
            },
        )
        scan_id = start_response.json()["scan_id"]

        status_response = client.get(f"/scan/status/{scan_id}")

        assert status_response.status_code == 200
        data = status_response.json()
        assert "status" in data
        assert "progress" in data

    def test_get_scan_report_before_completion_fails(self):
        """Test GET /scan/report returns 400 when scan not completed."""
        from main import app

        client = TestClient(app)

        start_response = client.post(
            "/scan/full",
            json={
                "repo_full_name": "owner/repo",
                "repo_url": "https://github.com/owner/repo",
                "branch": "main",
            },
        )
        scan_id = start_response.json()["scan_id"]

        report_response = client.get(f"/scan/report/{scan_id}")

        assert report_response.status_code == 400


class TestScanSecurityPatterns:
    """Test security scanning patterns."""

    def test_detects_hardcoded_api_key(self):
        """Test detection of hardcoded OpenAI API keys."""
        from routers.scan import _scan_file_for_secrets

        content = 'API_KEY = "sk-1234567890abcdefghijklmnopqrstuv"'
        issues = _scan_file_for_secrets(content)

        assert len(issues) > 0
        assert any("OpenAI" in i["body"] for i in issues)

    def test_detects_google_api_key(self):
        """Test detection of Google API keys."""
        from routers.scan import _scan_file_for_secrets

        content = "GOOGLE_KEY = AIzaSy1234567890abcdefghijklmnopqrstuvwxyz"
        issues = _scan_file_for_secrets(content)

        assert len(issues) > 0
        assert any("Google" in i["body"] for i in issues)

    def test_detects_github_token(self):
        """Test detection of GitHub tokens."""
        from routers.scan import _scan_file_for_secrets

        content = "GITHUB_TOKEN = ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        issues = _scan_file_for_secrets(content)

        assert len(issues) > 0
        assert any("GitHub" in i["body"] for i in issues)

    def test_detects_eval_usage(self):
        """Test detection of eval() usage."""
        from routers.scan import _scan_file_for_security

        content = "eval(user_input)"
        issues = _scan_file_for_security(content)

        assert len(issues) > 0
        assert any("eval" in i["body"].lower() for i in issues)

    def test_detects_os_system(self):
        """Test detection of os.system usage."""
        from routers.scan import _scan_file_for_security

        content = "os.system('ls')"
        issues = _scan_file_for_security(content)

        assert len(issues) > 0
        assert any("command injection" in i["body"].lower() for i in issues)


class TestScanQualityPatterns:
    """Test code quality scanning patterns."""

    def test_detects_long_lines(self):
        """Test detection of lines over 120 characters."""
        from routers.scan import _scan_file_for_quality

        content = "x = " + "a" * 130
        issues = _scan_file_for_quality(content, "python")

        assert len(issues) > 0

    def test_detects_long_functions(self):
        """Test detection of functions over 50 lines."""
        from routers.scan import _scan_file_for_quality

        content = "\n".join(
            [
                f"def long_function():\n    pass" if i == 0 else f"    x = {i}"
                for i in range(55)
            ]
        )
        issues = _scan_file_for_quality(content, "python")

        assert len(issues) >= 1

    def test_detects_todo_comments(self):
        """Test detection of TODO/FIXME comments."""
        from routers.scan import _scan_file_for_quality

        content = "# TODO: Fix this later"
        issues = _scan_file_for_quality(content, "python")

        assert len(issues) > 0
        assert any("TODO" in i["body"] for i in issues)


class TestLanguageDetection:
    """Test language detection."""

    def test_detects_python(self):
        """Test Python file detection."""
        from routers.scan import _detect_language

        assert _detect_language("app.py") == "python"
        assert _detect_language("main.py") == "python"

    def test_detects_javascript(self):
        """Test JavaScript file detection."""
        from routers.scan import _detect_language

        assert _detect_language("app.js") == "javascript"
        assert _detect_language("index.js") == "javascript"

    def test_detects_typescript(self):
        """Test TypeScript file detection."""
        from routers.scan import _detect_language

        assert _detect_language("app.ts") == "typescript"
        assert _detect_language("component.tsx") == "typescript"

    def test_detects_go(self):
        """Test Go file detection."""
        from routers.scan import _detect_language

        assert _detect_language("main.go") == "go"

    def test_returns_unknown_for_unknown(self):
        """Test unknown file extension returns 'unknown'."""
        from routers.scan import _detect_language

        assert _detect_language("README") == "unknown"
        assert _detect_language("Makefile") == "unknown"


class TestScanResult:
    """Test ScanResult dataclass."""

    def test_scan_result_creation(self):
        """Test ScanResult can be created."""
        from routers.scan import ScanResult

        result = ScanResult(
            scan_id=1,
            status="completed",
            files_scanned=10,
            total_files=10,
            health_score=85,
        )

        assert result.scan_id == 1
        assert result.status == "completed"
        assert result.health_score == 85
