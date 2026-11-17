import json
from pathlib import Path

import pytest

from rynsy_rules.features import problems
from rynsy_rules.runs import unpassed

PROOFS = """
import os

import pytest


def test_passes():
    assert True


def test_fails():
    assert os.environ.get("RYP_NEVER_SET")


@pytest.mark.parametrize("x", [1, 2])
def test_param(x):
    assert x < 2


class TestGroup:
    def test_member(self):
        assert self
"""

SKIP_EVERYTHING = """
import pytest


@pytest.fixture(autouse=True)
def _no_docker():
    pytest.skip("Docker not available")
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "test_proofs.py").write_text(PROOFS, encoding="utf-8")
    return tmp_path


def test_only_proofs_that_ran_and_passed_count(repo: Path) -> None:
    found = unpassed(
        repo,
        [
            "tests/unit/test_proofs.py::test_passes",
            "tests/unit/test_proofs.py::TestGroup::test_member",
            "tests/unit/test_proofs.py::test_param[1]",
            "tests/unit/test_proofs.py::test_param",
            "tests/unit/test_proofs.py::test_fails",
        ],
    )
    assert found == {
        "tests/unit/test_proofs.py::test_param": "did not pass when run (failed, passed)",
        "tests/unit/test_proofs.py::test_fails": "did not pass when run (failed)",
    }


def test_a_proof_pytest_cannot_collect_did_not_run(repo: Path) -> None:
    found = unpassed(repo, ["tests/unit/test_proofs.py::test_missing"])
    assert found["tests/unit/test_proofs.py::test_missing"].startswith("did not run when collected by pytest")


def test_a_fixture_that_skips_everything_is_caught(repo: Path) -> None:
    (repo / "tests" / "unit" / "conftest.py").write_text(SKIP_EVERYTHING, encoding="utf-8")
    (repo / "openapi.json").write_text(
        json.dumps({"paths": {"/a": {"get": {"operationId": "a"}}}}), encoding="utf-8"
    )
    proof = "tests/unit/test_proofs.py::test_passes"
    (repo / "features.json").write_text(
        json.dumps([{"name": "A", "operations": ["a"], "provenBy": [proof]}]), encoding="utf-8"
    )
    found = list(problems(repo, repo / "openapi.json", repo / "features.json"))
    assert found == [f"feature 'A': {proof}: did not pass when run (skipped)"]


def test_no_proofs_runs_nothing(tmp_path: Path) -> None:
    assert unpassed(tmp_path, []) == {}
