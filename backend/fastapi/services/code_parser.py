"""
Code parser for parsing Git diffs into structured chunks.

Parses unified diff format and extracts language, changes, and context.
"""

import re
import sys
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
class DiffLine:
    """One line of a hunk. ``new_line`` is None for removed lines."""

    kind: str  # "added", "removed" or "context"
    content: str
    new_line: Optional[int] = None
    old_line: Optional[int] = None


@dataclass
class DiffHunk:
    """One ``@@`` hunk with its lines in diff order."""

    header: str
    new_start: int
    lines: list[DiffLine] = field(default_factory=list)


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
    hunks: list[DiffHunk] = field(default_factory=list)


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


HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _header_path(line: str, prefix: str) -> Optional[str]:
    """Path from a ``---``/``+++`` header line; None for /dev/null."""
    path = line[4:].split("\t")[0].strip()
    if path == "/dev/null":
        return None
    if path.startswith(prefix):
        path = path[len(prefix) :]
    return path


def parse_diff(diff_text: str) -> list[DiffChunk]:
    """
    Parse unified diff format into structured chunks.

    Produces one chunk per changed file. Each chunk keeps its hunks, and every
    added and context line records its line number in the new file.

    Args:
        diff_text: Unified diff text (from GitHub API or git diff)

    Returns:
        List of DiffChunk objects
    """
    chunks: list[DiffChunk] = []
    current: Optional[DiffChunk] = None
    hunk: Optional[DiffHunk] = None
    old_no = new_no = 0
    old_remaining = new_remaining = 0
    numbered = False

    def flush() -> None:
        if (
            current
            and current.file_path
            and (current.added_lines or current.removed_lines)
        ):
            chunks.append(current)

    lines = diff_text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    i = 0
    while i < len(lines):
        line = lines[i]
        in_hunk = hunk is not None and (old_remaining > 0 or new_remaining > 0)

        if line.startswith("diff --git "):
            flush()
            current, hunk = None, None
            i += 1
            continue

        # "--- "/"+++ " can also be a removed "-- x" or added "++ y" line, so
        # inside a hunk they only count as a file header when a hunk header
        # follows and these two lines would not exactly finish the hunk.
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        if line.startswith("--- ") and next_line.startswith("+++ "):
            after = lines[i + 2] if i + 2 < len(lines) else ""
            if not in_hunk or (
                after.startswith("@@")
                and not (old_remaining == 1 and new_remaining == 1)
            ):
                flush()
                old_path = _header_path(line, "a/")
                file_path = _header_path(next_line, "b/") or old_path or ""
                current = DiffChunk(
                    file_path=file_path,
                    added_lines=[],
                    removed_lines=[],
                    context_lines=[],
                    language=detect_language(file_path),
                    chunk_type="file",
                    old_path=old_path,
                )
                hunk = None
                i += 2
                continue

        if line.startswith("@@"):
            match = HUNK_HEADER_RE.match(line)
            if match:
                old_no, new_no = int(match.group(1)), int(match.group(3))
                old_remaining = int(match.group(2) or 1)
                new_remaining = int(match.group(4) or 1)
                numbered = True
            else:
                old_no = new_no = 0
                old_remaining = new_remaining = sys.maxsize
                numbered = False
            hunk = DiffHunk(header=line, new_start=new_no)
            if current is not None:
                current.hunks.append(hunk)
                current.hunk_header = line
            i += 1
            continue

        i += 1
        if not in_hunk or current is None or hunk is None:
            continue

        if line.startswith("\\"):
            # "\ No newline at end of file" describes the previous line.
            continue

        if line.startswith("+"):
            hunk.lines.append(
                DiffLine("added", line[1:], new_line=new_no if numbered else None)
            )
            current.added_lines.append(line[1:])
            new_no += 1
            new_remaining -= 1
        elif line.startswith("-"):
            hunk.lines.append(
                DiffLine("removed", line[1:], old_line=old_no if numbered else None)
            )
            current.removed_lines.append(line[1:])
            old_no += 1
            old_remaining -= 1
        elif line.startswith(" ") or line == "":
            hunk.lines.append(
                DiffLine(
                    "context",
                    line[1:],
                    new_line=new_no if numbered else None,
                    old_line=old_no if numbered else None,
                )
            )
            current.context_lines.append(line[1:])
            new_no += 1
            old_no += 1
            new_remaining -= 1
            old_remaining -= 1
        else:
            hunk = None

    flush()
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
