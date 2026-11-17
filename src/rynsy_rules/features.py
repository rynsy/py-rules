import ast
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TypedDict

from rynsy_rules import runs


class Feature(TypedDict):
    name: str
    operations: list[str]
    provenBy: list[str]


def load_features(path: Path) -> list[Feature]:
    features: list[Feature] = json.loads(path.read_text(encoding="utf-8"))
    return features


def operations(openapi: Path) -> tuple[dict[str, str], list[str]]:
    """Map operationId to "METHOD /path"; list operations with no id and ids used twice."""
    doc = json.loads(openapi.read_text(encoding="utf-8"))
    named: dict[str, str] = {}
    wrong: list[str] = []
    for route, ops in doc["paths"].items():
        for method, op in ops.items():
            if method not in HTTP_METHODS:
                continue
            label = f"{method.upper()} {route}"
            op_id = op.get("operationId")
            if op_id is None:
                wrong.append(f"operation {label} has no operationId, so no feature can claim it")
            elif op_id in named:
                first, second = sorted((named[op_id], label))
                wrong.append(f"operationId {op_id} is used by both {first} and {second}")
            else:
                named[op_id] = label
    return named, sorted(wrong)


HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
SKIPPING = re.compile(r"\b(skip|skipif|xfail|importorskip)\b")
TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")


def _skipping_aliases(tree: ast.Module) -> set[str]:
    aliases: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and SKIPPING.search(ast.unparse(node.value)):
            aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return aliases


def _skips(node: ast.AST, aliases: set[str]) -> bool:
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return False
    for decorator in node.decorator_list:
        root = decorator.func if isinstance(decorator, ast.Call) else decorator
        if SKIPPING.search(ast.unparse(decorator)) or (isinstance(root, ast.Name) and root.id in aliases):
            return True
    return False


def _body_skips(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(inner, ast.Call) and SKIPPING.search(ast.unparse(inner.func)) for inner in ast.walk(node)
    )


def _asserts(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Assert):
            return True
        if isinstance(inner, ast.Call):
            name = ast.unparse(inner.func).rsplit(".", 1)[-1]
            if name.startswith("assert") or name == "raises":
                return True
    return False


def _verdict(node: ast.FunctionDef | ast.AsyncFunctionDef, *, skipped: bool, aliases: set[str]) -> str | None:
    if skipped or _skips(node, aliases) or _body_skips(node):
        return "the test is skipped or xfail, so it proves nothing"
    if not _asserts(node):
        return "the test asserts nothing, so it proves nothing"
    return None


def _tests_in(path: Path) -> dict[str, str | None]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    aliases = _skipping_aliases(tree)
    module_skipped = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
        and SKIPPING.search(ast.unparse(node.value))
        for node in tree.body
    )
    found: dict[str, str | None] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
            found[node.name] = _verdict(node, skipped=module_skipped, aliases=aliases)
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_skipped = module_skipped or _skips(node, aliases)
            for member in node.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and member.name.startswith(
                    "test"
                ):
                    found[f"{node.name}::{member.name}"] = _verdict(
                        member, skipped=class_skipped, aliases=aliases
                    )
    return found


def proof_problem(root: Path, node_id: str) -> str | None:
    file_part, _, name = node_id.partition("::")
    path = root / file_part
    if not name or not TEST_FILE.search(file_part) or not path.is_file():
        return f"{node_id}: not a pytest node id of an existing test file (tests/x/test_y.py::test_name)"
    tests = _tests_in(path)
    key = name.split("[", 1)[0]
    if key not in tests:
        return f"{node_id}: no such test function"
    verdict = tests[key]
    return f"{node_id}: {verdict}" if verdict else None


def declared_statuses(openapi: Path) -> dict[str, set[str]]:
    """Map each operationId to the response status codes it declares."""
    doc = json.loads(openapi.read_text(encoding="utf-8"))
    return {
        op["operationId"]: {str(code) for code in op.get("responses", {})}
        for ops in doc["paths"].values()
        for method, op in ops.items()
        if method in HTTP_METHODS and "operationId" in op
    }


def problems(root: Path, openapi: Path, features_path: Path, *, run_proofs: bool = True) -> Iterator[str]:
    ops, wrong = operations(openapi)
    yield from wrong
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
    if run_proofs:
        yield from _run_problems(root, features)


def _run_problems(root: Path, features: list[Feature]) -> Iterator[str]:
    runnable = sorted(
        {
            node_id
            for feature in features
            for node_id in feature["provenBy"]
            if not proof_problem(root, node_id)
        }
    )
    failed = runs.unpassed(root, runnable)
    for feature in features:
        for node_id in feature["provenBy"]:
            if node_id in failed:
                yield f"feature '{feature['name']}': {node_id}: {failed[node_id]}"
