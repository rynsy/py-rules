import os
import subprocess
import sys
from pathlib import Path

import pytest

from rynsy_rules.cli import main

PYPROJECT = """
[project]
name = "consumer"
version = "0.0.0"
requires-python = ">=3.13"

[tool.ruff]
extend = ".ruff-rynsy.toml"
src = ["src", "tests"]
"""

PRODUCT = '''"""Product code."""

import time
from datetime import UTC, datetime


def stamp() -> datetime:
    """Return now."""
    time.sleep(1)
    return datetime.now(UTC)
'''


@pytest.fixture
def consumer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    for relative in ("src/consumer/clock.py", "src/consumer/main.py", "tests/test_clock.py"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(PRODUCT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["config"]) == 0
    return tmp_path


def banned(consumer: Path) -> list[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("RUFF")}
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "TID251", "--output-format", "concise", "."],
        cwd=consumer,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return [
        line.split(":", 2)[0] + ":" + line.split(":", 2)[1]
        for line in result.stdout.splitlines()
        if "TID251" in line
    ]


def test_config_is_written_at_the_root(consumer: Path) -> None:
    assert (consumer / ".ruff-rynsy.toml").is_file()


def test_banned_apis_fire_in_product_code_only(consumer: Path) -> None:
    assert banned(consumer) == ["src/consumer/clock.py:9", "src/consumer/clock.py:10"]
