import ast
import json
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict


class Feature(TypedDict):
    name: str
    operations: list[str]
    provenBy: list[str]


def load_features(path: Path) -> list[Feature]:
    features: list[Feature] = json.loads(path.read_text(encoding="utf-8"))
    return features


def operation_ids(openapi: Path) -> dict[str, str]:
    doc = json.loads(openapi.read_text(encoding="utf-8"))
    return {
        op["operationId"]: f"{method.upper()} {route}"
        for route, ops in doc["paths"].items()
        for method, op in ops.items()
        if isinstance(op, dict) and "operationId" in op
    }


def _is_skipped(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in {"skip", "skipif", "xfail"}:
            return True
    return False


def _is_test(node: ast.stmt) -> bool:
    return isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test")


def _tests_in(path: Path) -> dict[str, bool]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, bool] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _is_test(node):
            found[node.name] = _is_skipped(node)
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for member in node.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and _is_test(member):
                    found[f"{node.name}::{member.name}"] = _is_skipped(member)
    return found


def proof_problem(root: Path, node_id: str) -> str | None:
    file_part, _, name = node_id.partition("::")
    path = root / file_part
    if not name or not file_part.endswith(".py") or not path.is_file():
        return f"{node_id}: not a pytest node id of an existing file (tests/x/test_y.py::test_name)"
    tests = _tests_in(path)
    key = name.split("[", 1)[0]
    if key not in tests:
        return f"{node_id}: no such test function"
    if tests[key]:
        return f"{node_id}: the test is skipped or xfail, so it proves nothing"
    return None


def problems(root: Path, openapi: Path, features_path: Path) -> Iterator[str]:
    ops = operation_ids(openapi)
    features = load_features(features_path)
    covered = {op for feature in features for op in feature["operations"]}
    for op in sorted(set(ops) - covered):
        yield f"operation {op} ({ops[op]}) belongs to no feature in {features_path}"
    for feature in features:
        for op in feature["operations"]:
            if op not in ops:
                yield f"feature '{feature['name']}': operation {op} is not in {openapi}"
        if not feature["provenBy"]:
            yield f"feature '{feature['name']}': no test proves it"
        for node_id in feature["provenBy"]:
            problem = proof_problem(root, node_id)
            if problem:
                yield f"feature '{feature['name']}': {problem}"
