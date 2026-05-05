"""
Code parser for parsing Git diffs into structured chunks.

Parses unified diff format and extracts language, changes, and context.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".sql": "sql",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}


SHEBANG_TO_LANGUAGE = {
    "python": ["python", "python3", "pypy"],
    "bash": ["bash", "sh", "zsh"],
    "ruby": ["ruby"],
    "perl": ["perl"],
    "php": ["php"],
}


LANGUAGE_KEYWORDS = {
    "python": ["def ", "class ", "import ", "from ", "async def ", "await "],
    "javascript": ["function ", "const ", "let ", "var ", "import ", "export ", "=>"],
    "typescript": [
        "function ",
        "const ",
        "let ",
        "var ",
        "import ",
        "export ",
        "interface ",
        "type ",
    ],
    "go": ["func ", "package ", "import ", "type ", "struct "],
    "rust": ["fn ", "let ", "mut ", "impl ", "pub ", "use "],
    "java": ["public class ", "private ", "protected ", "import java"],
}


@dataclass
class DiffChunk:
    """A parsed diff chunk for a single file/hunk."""

    file_path: str
    added_lines: list[str]
    removed_lines: list[str]
    context_lines: list[str]
    language: str
    chunk_type: str
    hunk_header: str = ""
    old_path: Optional[str] = None


def detect_language(file_path: str, content: str = "") -> str:
    """
    Detect programming language from file extension or content.

    Args:
        file_path: File path (may include extension)
        content: Optional file content for heuristic detection

    Returns:
        Language string (e.g., "python", "typescript", "unknown")
    """
    ext = get_extension(file_path)
    if ext in EXTENSION_TO_LANGUAGE:
        return EXTENSION_TO_LANGUAGE[ext]

    if content:
        if content.startswith("#!"):
            shebang = content.split("\n")[0]
            for lang, commands in SHEBANG_TO_LANGUAGE.items():
                if any(cmd in shebang for cmd in commands):
                    return lang

        first_lines = "\n".join(content.split("\n")[:20])
        for lang, keywords in LANGUAGE_KEYWORDS.items():
            if all(kw in first_lines for kw in keywords[:2]):
                return lang

    return "unknown"


def get_extension(file_path: str) -> str:
    """Extract file extension from path."""
    if "." in file_path:
        return "." + file_path.rsplit(".", 1)[-1]
    return ""


def chunk_into_functions(code: str, language: str) -> list[str]:
    """
    Split code into function/class chunks.

    Args:
        code: Source code
        language: Programming language

    Returns:
        List of code chunks (functions, classes, etc.)
    """
    chunks = []

    if language == "python":
        pattern = r"^(def |class |async def )"
    elif language == "javascript":
        pattern = r"^(function |const |class |let |var )"
    elif language == "typescript":
        pattern = r"^(function |const |class |interface |type |let |var )"
    elif language == "go":
        pattern = r"^func |^type |^package "
    elif language == "rust":
        pattern = r"^fn |^struct |^impl |^pub |^let "
    else:
        return [code]

    lines = code.split("\n")
    current_chunk = []

    for line in lines:
        if re.match(pattern, line.strip()):
            if current_chunk:
                chunks.append("\n".join(current_chunk))
            current_chunk = [line]
        elif current_chunk:
            current_chunk.append(line)

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks if chunks else [code]


def parse_diff(diff_text: str) -> list[DiffChunk]:
    """
    Parse unified diff format into structured chunks.

    Args:
        diff_text: Unified diff text (from GitHub API or git diff)

    Returns:
        List of DiffChunk objects
    """
    chunks: list[DiffChunk] = []
    current_file: Optional[str] = None
    current_hunk: str = ""
    added_lines: list[str] = []
    removed_lines: list[str] = []
    context_lines: list[str] = []
    current_language: str = "unknown"
    current_chunk_type: str = "file"
    old_path: Optional[str] = None

    for line in diff_text.split("\n"):
        if not line:
            continue

        if line.startswith("+++") or line.startswith("---"):
            if current_file and (added_lines or removed_lines):
                chunks.append(
                    DiffChunk(
                        file_path=current_file,
                        added_lines=added_lines,
                        removed_lines=removed_lines,
                        context_lines=context_lines,
                        language=current_language,
                        chunk_type=current_chunk_type,
                        hunk_header=current_hunk,
                        old_path=old_path,
                    )
                )
                added_lines = []
                removed_lines = []
                context_lines = []
                current_hunk = ""

            if line.startswith("+++ b/") or line.startswith("+++ "):
                current_file = line.replace("+++ b/", "").replace("+++ ", "").strip()
            elif line.startswith("--- a/") or line.startswith("--- "):
                old_path = line.replace("--- a/", "").replace("--- ", "").strip()
                if current_file is None:
                    current_file = old_path
                current_file = old_path

            language = detect_language(current_file or "")
            current_language = language
            continue

        if line.startswith("@@"):
            current_hunk = line
            continue

        if line.startswith("+"):
            added_lines.append(line[1:])
        elif line.startswith("-"):
            removed_lines.append(line[1:])
        elif line.startswith(" ") or line.startswith("\t"):
            context_lines.append(line[1:] if len(line) > 1 else "")

    if current_file and (added_lines or removed_lines):
        chunks.append(
            DiffChunk(
                file_path=current_file,
                added_lines=added_lines,
                removed_lines=removed_lines,
                context_lines=context_lines,
                language=current_language,
                chunk_type=current_chunk_type,
                hunk_header=current_hunk,
                old_path=old_path,
            )
        )

    return chunks


def parse_unified_diff(raw_diff: str) -> list[DiffChunk]:
    """
    Parse unified diff with full context.

    Args:
        raw_diff: Full diff text

    Returns:
        List of DiffChunk with context preserved
    """
    return parse_diff(raw_diff)
