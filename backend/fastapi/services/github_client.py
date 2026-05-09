"""
GitHub API client for FastAPI service.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


@dataclass
class GitHubFile:
    """Represents a file in a GitHub repository."""

    path: str
    content: str
    language: str
    size: int


class GitHubClientError(Exception):
    """Raised when GitHub API call fails."""

    pass


class GitHubClient:
    """GitHub API client for fetching repository contents."""

    def __init__(self, token: str | None = None):
        self.token = token
        self._session = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            timeout=30.0,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _get_headers(self) -> dict[str, str]:
        """Get headers with optional auth."""
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def get_repository_tree(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Get repository tree recursively.

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch name
            recursive: Get all files recursively

        Returns:
            List of tree entries
        """
        params = {"recursive": 1} if recursive else {}

        try:
            response = await self._session.get(
                f"/repos/{owner}/{repo}/git/trees/{branch}",
                params=params,
                headers=self._get_headers(),
            )

            if response.status_code == 404:
                raise GitHubClientError(f"Repository not found: {owner}/{repo}")

            if response.status_code == 403:
                raise GitHubClientError("Rate limit or permission denied")

            if response.status_code != 200:
                raise GitHubClientError(f"GitHub API error: {response.status_code}")

            data = response.json()
            return data.get("tree", [])

        except httpx.HTTPError as e:
            raise GitHubClientError(f"HTTP error: {e}")

    async def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "main",
    ) -> str:
        """
        Get file content from repository.

        Args:
            owner: Repository owner
            repo: Repository name
            path: File path
            ref: Branch/commit SHA

        Returns:
            File content as string
        """
        try:
            response = await self._session.get(
                f"/repos/{owner}/{repo}/contents/{path}",
                params={"ref": ref},
                headers=self._get_headers(),
            )

            if response.status_code == 404:
                raise GitHubClientError(f"File not found: {path}")

            if response.status_code == 403:
                raise GitHubClientError("Rate limit or permission denied")

            if response.status_code != 200:
                raise GitHubClientError(f"GitHub API error: {response.status_code}")

            data = response.json()

            if isinstance(data.get("content"), str):
                import base64

                content = data["content"]
                encoding = data.get("encoding", "base64")

                if encoding == "base64":
                    decoded = base64.b64decode(content).decode("utf-8")
                    return decoded

            return str(data.get("content", ""))

        except httpx.HTTPError as e:
            raise GitHubClientError(f"HTTP error: {e}")

    async def get_file_content_base64(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "main",
    ) -> str:
        """
        Get file content as base64 encoded.

        Args:
            owner: Repository owner
            repo: Repository name
            path: File path
            ref: Branch/commit SHA

        Returns:
            Base64 encoded file content
        """
        try:
            response = await self._session.get(
                f"/repos/{owner}/{repo}/contents/{path}",
                params={"ref": ref},
                headers=self._get_headers(),
            )

            if response.status_code != 200:
                return ""

            data = response.json()
            return data.get("content", "").replace("\n", "")

        except Exception:
            return ""

    async def get_default_branch(self, owner: str, repo: str) -> str:
        """
        Get the default branch of a repository.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Default branch name (usually 'main' or 'master')
        """
        try:
            response = await self._session.get(
                f"/repos/{owner}/{repo}",
                headers=self._get_headers(),
            )

            if response.status_code != 200:
                return "main"

            data = response.json()
            return data.get("default_branch", "main")

        except Exception:
            return "main"

    async def close(self) -> None:
        """Close the HTTP session."""
        await self._session.aclose()


# Filter patterns to skip during scanning
SKIP_PATTERNS = [
    # Build artifacts
    "node_modules/",
    ".git/",
    "__pycache__/",
    ".venv/",
    "venv/",
    "dist/",
    "build/",
    ".next/",
    ".nuxt/",
    "out/",
    # Dependencies
    "vendor/",
    "packages/",
    ".npm/",
    ".cache/",
    # Configuration (usually not code to review)
    ".github/",
    ".gitignore",
    ".dockerignore",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    # Documentation
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "*.md",
]

# File extensions to include for scanning
CODE_EXTENSIONS = {
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
    ".jsx": "javascript",
    ".sql": "sql",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
}


def should_skip_path(path: str) -> bool:
    """Check if path should be skipped during scanning."""
    for pattern in SKIP_PATTERNS:
        if pattern.endswith("/"):
            if pattern[:-1] in path or path.startswith(pattern):
                return True
        elif path.endswith(pattern.replace("*", "")):
            return True

    # Skip files without code extensions
    has_code_ext = any(path.endswith(ext) for ext in CODE_EXTENSIONS)
    return not has_code_ext


def get_language(path: str) -> str:
    """Detect language from file extension."""
    for ext, lang in CODE_EXTENSIONS.items():
        if path.endswith(ext):
            return lang
    return "unknown"
