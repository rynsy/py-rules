import json
from pathlib import Path

import pytest

from rynsy_rules.features import problems

TESTS = """
import pytest

def test_round_trip():
    pass

@pytest.mark.skip(reason="later")
def test_skipped():
    pass

@pytest.mark.parametrize("x", [1])
def test_param(x):
    pass

class TestGroup:
    async def test_member(self):
        pass

def helper():
    pass
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api.py").write_text(TESTS, encoding="utf-8")
    openapi = {
        "paths": {
            "/v1/sync": {"post": {"operationId": "startSync"}, "parameters": []},
            "/v1/items": {"get": {"operationId": "listItems"}},
        }
    }
    (tmp_path / "openapi.json").write_text(json.dumps(openapi), encoding="utf-8")
    return tmp_path


def run(repo: Path, features: list[dict[str, object]]) -> list[str]:
    (repo / "features.json").write_text(json.dumps(features), encoding="utf-8")
    return list(problems(repo, repo / "openapi.json", repo / "features.json"))


def feature(operations: list[str], proven_by: list[str]) -> dict[str, object]:
    return {"name": "F", "operations": operations, "provenBy": proven_by}


def test_a_complete_map_has_no_problems(repo: Path) -> None:
    proofs = [
        "tests/test_api.py::test_round_trip",
        "tests/test_api.py::test_param[1]",
        "tests/test_api.py::TestGroup::test_member",
    ]
    assert run(repo, [feature(["startSync", "listItems"], proofs)]) == []


@pytest.mark.parametrize(
    ("operations", "proofs", "expected"),
    [
        (
            ["startSync"],
            ["tests/test_api.py::test_round_trip"],
            "operation listItems (GET /v1/items) belongs",
        ),
        (
            ["startSync", "listItems", "gone"],
            ["tests/test_api.py::test_round_trip"],
            "operation gone is not in",
        ),
        (["startSync", "listItems"], [], "no test proves it"),
        (["startSync", "listItems"], ["tests/test_api.py::helper"], "no such test function"),
        (["startSync", "listItems"], ["tests/test_api.py::test_missing"], "no such test function"),
        (["startSync", "listItems"], ["tests/test_api.py::test_skipped"], "skipped or xfail"),
        (["startSync", "listItems"], ["tests/test_nope.py::test_round_trip"], "not a pytest node id"),
        (["startSync", "listItems"], ["test_round_trip"], "not a pytest node id"),
    ],
)
def test_each_gap_is_reported(repo: Path, operations: list[str], proofs: list[str], expected: str) -> None:
    found = run(repo, [feature(operations, proofs)])
    assert len(found) == 1
    assert expected in found[0]
