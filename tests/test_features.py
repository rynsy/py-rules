import json
from pathlib import Path

import pytest

from rynsy_rules.features import problems

TESTS = """
import pytest
from pytest import mark

skip_it = pytest.mark.skip

def test_round_trip():
    assert 1 + 1 == 2

@pytest.mark.skip(reason="later")
def test_skipped():
    assert True

@mark.xfail
def test_xfail():
    assert True

@skip_it
def test_alias_skipped():
    assert True

def test_skips_inside():
    pytest.skip("later")
    assert True

def test_proves_nothing():
    pass

def test_raises():
    with pytest.raises(ValueError):
        int("x")

def test_helper_assert(mock):
    mock.assert_called_once()

@pytest.mark.parametrize("x", [1])
def test_param(x):
    assert x

class TestGroup:
    async def test_member(self):
        assert self

@pytest.mark.skip
class TestSkipped:
    def test_inside(self):
        assert self

def helper():
    assert True
"""

SKIPPED_MODULE = """
import pytest

pytestmark = pytest.mark.skip

def test_anything():
    assert True
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_api.py").write_text(TESTS, encoding="utf-8")
    (tmp_path / "tests" / "test_off.py").write_text(SKIPPED_MODULE, encoding="utf-8")
    (tmp_path / "tests" / "helpers.py").write_text("def test_helper():\n    assert True\n", encoding="utf-8")
    openapi = {
        "paths": {
            "/v1/sync": {"post": {"operationId": "startSync"}, "parameters": [], "summary": "s"},
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
        "tests/test_api.py::test_raises",
        "tests/test_api.py::test_helper_assert",
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
        (["startSync", "listItems"], ["tests/test_api.py::test_xfail"], "skipped or xfail"),
        (["startSync", "listItems"], ["tests/test_api.py::test_alias_skipped"], "skipped or xfail"),
        (["startSync", "listItems"], ["tests/test_api.py::test_skips_inside"], "skipped or xfail"),
        (["startSync", "listItems"], ["tests/test_api.py::TestSkipped::test_inside"], "skipped or xfail"),
        (["startSync", "listItems"], ["tests/test_off.py::test_anything"], "skipped or xfail"),
        (["startSync", "listItems"], ["tests/test_api.py::test_proves_nothing"], "asserts nothing"),
        (["startSync", "listItems"], ["tests/helpers.py::test_helper"], "not a pytest node id"),
        (["startSync", "listItems"], ["tests/test_nope.py::test_round_trip"], "not a pytest node id"),
        (["startSync", "listItems"], ["test_round_trip"], "not a pytest node id"),
    ],
)
def test_each_gap_is_reported(repo: Path, operations: list[str], proofs: list[str], expected: str) -> None:
    found = run(repo, [feature(operations, proofs)])
    assert len(found) == 1
    assert expected in found[0]


def test_an_operation_without_an_id_is_reported(repo: Path) -> None:
    openapi = {"paths": {"/v1/x": {"get": {"summary": "no id"}}}}
    (repo / "openapi.json").write_text(json.dumps(openapi), encoding="utf-8")
    found = run(repo, [])
    assert found == ["operation GET /v1/x has no operationId, so no feature can claim it"]


def test_a_duplicate_operation_id_is_reported(repo: Path) -> None:
    openapi = {"paths": {"/a": {"get": {"operationId": "op"}}, "/b": {"post": {"operationId": "op"}}}}
    (repo / "openapi.json").write_text(json.dumps(openapi), encoding="utf-8")
    found = run(repo, [feature(["op"], ["tests/test_api.py::test_round_trip"])])
    assert found == ["operationId op is used by both GET /a and POST /b"]
