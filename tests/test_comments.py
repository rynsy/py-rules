from pathlib import Path

import pytest

from rynsy_rules.comments import check_paths, check_source


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
