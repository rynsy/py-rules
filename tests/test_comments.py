import subprocess
from pathlib import Path

import pytest

from rynsy_rules.comments import check_paths, check_pyproject, check_source


def rules(source: str) -> list[str]:
    return [f"{f.rule}@{f.line}" for f in check_source(Path("x.py"), source)]


@pytest.mark.parametrize(
    "source",
    [
        "x = 1\n",
        "#!/usr/bin/env python3\nx = 1\n",
        "x = 1  # TODO(#12) replace with the batch endpoint\n",
        "# ponytail: global lock, per-account locks if throughput matters\n",
        "x = 1  # noqa: S104  TODO(#3)\n",
        "x = 1  # type: ignore[arg-type]  # TODO(#4)\n",
        's = "# not a comment"\n',
        "# ponytail: one line\n# that continues\n# for a while\nx = 1\n",
        "def f():\n    # TODO(#7) the batch endpoint\n    # once it ships\n    return 1\n",
        '"""Module."""\n\n\nclass C:\n    """Class."""\n\n    def m(self):\n        """Method."""\n',
        'doc = """\n# inside a string\n"""\n',
    ],
)
def test_allowed(source: str) -> None:
    assert rules(source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("# explain the workaround\nx = 1\n", ["RYP001@1"]),
        ("x = 1  # because the API is slow\n", ["RYP001@1"]),
        ("# TODO: no issue\n", ["RYP001@1"]),
        ("# x = old_code()\n", ["RYP001@1"]),
        ("x = 1  # noqa: S104\n", ["RYP002@1"]),
        ("x = 1  # noqa: ASYNC240  (startup)\n", ["RYP002@1"]),
        ("x = 1  # type: ignore[arg-type]\n", ["RYP002@1"]),
        ("x = 1  # pragma: no cover\n", ["RYP002@1"]),
        ("# fmt: off\nx = 1\n# fmt: on\n", ["RYP002@1", "RYP002@3"]),
        ("x = 1\n#!/bin/sh\n", ["RYP001@2"]),
        ("# ponytail: a\n\n# after a blank line\n", ["RYP001@3"]),
        ("def f():\n    # ponytail: a\n# outdented\n    return 1\n", ["RYP001@3"]),
        ("x = 1  # ponytail: trailing\n# not a continuation\n", ["RYP001@2"]),
        ("# fine\n# ponytail: a\n", ["RYP001@1"]),
        ("x = 1  # TODO(#0) zero is not an issue\n", ["RYP001@1"]),
        ("# ponytail: a\n# b\n# c\n# d\n", ["RYP001@4"]),
        ("x = 1  # NOQA\n", ["RYP002@1"]),
        ("# ruff: noqa\n", ["RYP002@1"]),
        ('def f():\n    x = 1\n    "a comment in disguise"\n    return x\n', ["RYP003@3"]),
    ],
)
def test_flagged(source: str, expected: list[str]) -> None:
    assert rules(source) == expected


def test_walk_skips_virtualenvs_and_reports_each_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# bad\n", encoding="utf-8")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "b.py").write_text("# third party\n", encoding="utf-8")

    findings = check_paths([tmp_path])

    assert [(f.path.name, f.rule) for f in findings] == [("a.py", "RYP001")]
    assert str(findings[0]).endswith(":1:1: RYP001 " + findings[0].message)


def test_build_folders_inside_the_package_are_checked_and_stubs_too(tmp_path: Path) -> None:
    (tmp_path / "src" / "build").mkdir(parents=True)
    (tmp_path / "src" / "build" / "mod.py").write_text("# hidden\n", encoding="utf-8")
    (tmp_path / "src" / "types.pyi").write_text("# hidden\n", encoding="utf-8")
    assert sorted(f.path.name for f in check_paths([tmp_path])) == ["mod.py", "types.pyi"]


@pytest.mark.parametrize(
    ("ruff", "flagged"),
    [
        ('[tool.ruff.lint.extend-per-file-ignores]\n"src/**" = ["TID251"]\n', True),
        ('[tool.ruff.lint]\nextend-ignore = ["TID"]\n', True),
        ('[tool.ruff.lint.extend-per-file-ignores]\n"tests/conftest.py" = ["ASYNC110"]\n', False),
    ],
)
def test_a_repo_cannot_exempt_itself_from_the_bans(tmp_path: Path, ruff: str, flagged: bool) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(ruff, encoding="utf-8")
    assert [f.rule for f in check_pyproject(pyproject)] == (["RYP004"] if flagged else [])


def test_inside_a_git_repo_ignored_files_are_skipped(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("mutants/\n", encoding="utf-8")
    (tmp_path / "mutants").mkdir()
    (tmp_path / "mutants" / "copy.py").write_text("# generated\n", encoding="utf-8")
    (tmp_path / "mine.py").write_text("# mine\n", encoding="utf-8")
    assert [f.path.name for f in check_paths([tmp_path])] == ["mine.py"]
