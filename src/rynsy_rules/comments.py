import re
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ISSUE = re.compile(r"TODO\(#\d+\)")
ALLOWED = re.compile(r"#\s*(TODO\(#\d+\)|ponytail:)")
SUPPRESSION = re.compile(r"#\s*(noqa\b|type:\s*ignore\b|pragma:|fmt:\s*(off|on|skip)\b|pyright:|mypy:)")
SKIP_DIRS = frozenset({".venv", "venv", ".git", "build", "dist", "node_modules", "__pycache__"})

COMMENT_MESSAGE = (
    "comments are not allowed. Fix the root cause, or say it in a name, a type or a test. "
    "Deferred work is `# TODO(#<issue>)`; a deliberate simplification is `# ponytail: <ceiling>`"
)
SUPPRESSION_MESSAGE = (
    "inline suppression without an issue. Fix the finding; for a permanent, reviewed exception use "
    "per-file-ignores in pyproject.toml; otherwise add `# TODO(#<issue>)` on the same line"
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    column: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column + 1}: {self.rule} {self.message}"


def check_source(path: Path, source: str) -> Iterator[Finding]:
    lines = source.splitlines(keepends=True)
    tokens = tokenize.generate_tokens(iter(lines).__next__)
    allowed_block: tuple[int, int] | None = None
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        text = token.string
        row, column = token.start
        own_line = not token.line[:column].strip()
        continues_block = own_line and allowed_block == (row - 1, column)
        allowed_block = None
        if row == 1 and text.startswith("#!"):
            continue
        if SUPPRESSION.search(text):
            if not ISSUE.search(text):
                yield Finding(path, row, column, "RYP002", SUPPRESSION_MESSAGE)
            continue
        if ALLOWED.match(text) or continues_block:
            if own_line:
                allowed_block = (row, column)
            continue
        yield Finding(path, row, column, "RYP001", COMMENT_MESSAGE)


def python_files(roots: list[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        for path in sorted(root.rglob("*.py")):
            if not SKIP_DIRS.intersection(path.relative_to(root).parts[:-1]):
                yield path


def check_paths(roots: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in python_files(roots):
        findings.extend(check_source(path, path.read_text(encoding="utf-8")))
    return findings
