import ast
import re
import shutil
import subprocess
import tokenize
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ISSUE = re.compile(r"TODO\(#[1-9]\d*\)")
ALLOWED = re.compile(r"#\s*(TODO\(#[1-9]\d*\)|ponytail:)")
SUPPRESSION = re.compile(
    r"#\s*(noqa\b|type:\s*ignore\b|pragma:|fmt:\s*(off|on|skip)\b|pyright:|mypy:|ruff:)", re.IGNORECASE
)
SKIP_DIRS = frozenset({".venv", "venv", ".git", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"})
MAX_CONTINUATION = 2

COMMENT_MESSAGE = (
    "comments are not allowed. Fix the root cause, or say it in a name, a type or a test. "
    "Deferred work is `# TODO(#<issue>)`; a deliberate simplification is `# ponytail: <ceiling>` "
    f"(at most {MAX_CONTINUATION} continuation lines)"
)
SUPPRESSION_MESSAGE = (
    "inline suppression without an issue. Fix the finding; for a permanent, reviewed exception use "
    "per-file-ignores in pyproject.toml; otherwise add `# TODO(#<issue>)` on the same line"
)
STRING_MESSAGE = (
    "a bare string is a comment in disguise. Only a module, class or function docstring may stand alone"
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


def _comment_findings(path: Path, source: str) -> Iterator[Finding]:
    lines = source.splitlines(keepends=True)
    tokens = tokenize.generate_tokens(iter(lines).__next__)
    block: tuple[int, int, int] | None = None
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        text = token.string
        row, column = token.start
        own_line = not token.line[:column].strip()
        continues = (
            own_line and block is not None and block[:2] == (row - 1, column) and block[2] < MAX_CONTINUATION
        )
        previous, block = block, None
        if row == 1 and text.startswith("#!"):
            continue
        if SUPPRESSION.search(text):
            if not ISSUE.search(text):
                yield Finding(path, row, column, "RYP002", SUPPRESSION_MESSAGE)
            continue
        if ALLOWED.match(text):
            block = (row, column, 0) if own_line else None
            continue
        if continues and previous is not None:
            block = (row, column, previous[2] + 1)
            continue
        yield Finding(path, row, column, "RYP001", COMMENT_MESSAGE)


def _docstring_positions(tree: ast.Module) -> set[int]:
    positions: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                positions.add(id(first))
    return positions


def _string_findings(path: Path, source: str) -> Iterator[Finding]:
    tree = ast.parse(source)
    docstrings = _docstring_positions(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and id(node) not in docstrings
        ):
            yield Finding(path, node.lineno, node.col_offset, "RYP003", STRING_MESSAGE)


def check_source(path: Path, source: str) -> Iterator[Finding]:
    yield from _comment_findings(path, source)
    yield from _string_findings(path, source)


def _git_listed(root: Path) -> list[Path] | None:
    git = shutil.which("git")
    if git is None:
        return None
    listed = subprocess.run(
        [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.py", "*.pyi"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        return None
    return sorted(
        root / name for name in listed.stdout.decode().split("\0") if name and (root / name).is_file()
    )


def python_files(roots: list[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        listed = _git_listed(root)
        if listed is not None:
            yield from listed
            continue
        for path in sorted(p for pattern in ("*.py", "*.pyi") for p in root.rglob(pattern)):
            if not SKIP_DIRS.intersection(path.relative_to(root).parts[:-1]):
                yield path


def check_paths(roots: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in python_files(roots):
        findings.extend(check_source(path, path.read_text(encoding="utf-8")))
    return sorted(findings, key=lambda f: (str(f.path), f.line, f.column))


BAN_EXEMPTION_MESSAGE = (
    "exempts code from the banned APIs (TID251). The bans hold everywhere except tests/ and "
    "src/<pkg>/main.py; move the clock or the wait to the composition root, or change py-rules"
)


def _ignore_lists(lint: dict[str, object]) -> Iterator[tuple[str, list[str]]]:
    for key in ("ignore", "extend-ignore"):
        value = lint.get(key)
        if isinstance(value, list):
            yield key, [str(v) for v in value]
    for key in ("per-file-ignores", "extend-per-file-ignores"):
        value = lint.get(key)
        if isinstance(value, dict):
            for pattern, rules in value.items():
                yield f"{key} {pattern!r}", [str(r) for r in rules]


def check_pyproject(path: Path) -> Iterator[Finding]:
    ruff = tomllib.loads(path.read_text(encoding="utf-8")).get("tool", {}).get("ruff", {})
    lint = ruff.get("lint", {})
    for where, rules in _ignore_lists({**ruff, **lint}):
        if any("TID251".startswith(rule) for rule in rules if rule):
            yield Finding(path, 1, 0, "RYP004", f"[tool.ruff] {where} {BAN_EXEMPTION_MESSAGE}")
