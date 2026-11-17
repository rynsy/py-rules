import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from rynsy_rules.features import Feature

FuzzResults = dict[str, tuple[str, list[str]]]
REQUIRED_SMOKE = ("the service cannot reach the internet", "only the gateway is outside the sealed network")


ALLOWED_STATUSES = frozenset({"2xx", "3xx", "4xx", "502", "503", "504"})
CONFIG_RULE = (
    "schemathesis.toml may only hold [[operations]] tables that name operations "
    "(include-operation-id) and let them answer 502, 503 or 504 "
    "(checks.not_a_server_error.expected-statuses); "
    "the base URL and every other check stay on the command line"
)


def _operation_table_problems(index: int, table: object, ops: dict[str, set[str]]) -> list[str]:
    if not isinstance(table, dict) or set(table) != {"include-operation-id", "checks"}:
        return [f"[[operations]] #{index}: {CONFIG_RULE}"]
    names = table["include-operation-id"]
    if not isinstance(names, list) or not names:
        return [f"[[operations]] #{index}: include-operation-id must be a list of operationIds"]
    problems = [f"[[operations]] #{index}: {name} is not an operationId" for name in names if name not in ops]
    checks = table["checks"]
    statuses = (
        checks.get("not_a_server_error", {})
        if isinstance(checks, dict) and set(checks) == {"not_a_server_error"}
        else None
    )
    if not isinstance(statuses, dict) or set(statuses) != {"expected-statuses"}:
        return [*problems, f"[[operations]] #{index}: {CONFIG_RULE}"]
    allowed = set(map(str, statuses["expected-statuses"]))
    widened = sorted(allowed - ALLOWED_STATUSES)
    if widened:
        problems.append(f"[[operations]] #{index}: expected-statuses may not include {', '.join(widened)}")
    for name in names:
        undeclared = sorted(
            code for code in allowed - {"2xx", "3xx", "4xx"} if code not in ops.get(name, set())
        )
        if name in ops and undeclared:
            problems.append(
                f"[[operations]] #{index}: {name} does not declare {', '.join(undeclared)} in openapi.json; "
                "an allowed 5xx must be a documented answer"
            )
    return problems


def config_problems(config: Path, ops: dict[str, set[str]]) -> list[str]:
    """What is wrong with a repo's schemathesis.toml; a missing file is fine."""
    if not config.exists():
        return []
    doc = tomllib.loads(config.read_text(encoding="utf-8"))
    if set(doc) - {"operations"}:
        return [f"{config}: {CONFIG_RULE} (found {', '.join(sorted(set(doc) - {'operations'}))})"]
    tables = doc.get("operations", [])
    if not isinstance(tables, list):
        return [f"{config}: {CONFIG_RULE}"]
    return [f"{config}: {p}" for i, t in enumerate(tables, 1) for p in _operation_table_problems(i, t, ops)]


def fuzz_results(junit: Path) -> FuzzResults:
    if not junit.exists():
        return {}
    results: FuzzResults = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        problems = [
            f"{p.get('message', '')}\n{(p.text or '').strip()}".strip()
            for p in case
            if p.tag in {"failure", "error"}
        ]
        skipped = any(p.tag == "skipped" for p in case)
        status = "fail" if problems else "skipped" if skipped else "pass"
        results[case.get("name", "")] = (status, problems)
    return results


def feature_status(fuzz: FuzzResults, ops: dict[str, str], feature: Feature) -> str:
    statuses = [fuzz.get(ops.get(op, ""), ("not run", []))[0] for op in feature["operations"]]
    if not statuses:
        return "not run"
    return next((s for s in ("fail", "not run", "skipped") if s in statuses), "pass")


def _section(title: str, failures: dict[str, list[str]]) -> list[str]:
    lines = ["", f"## {title}"]
    for name, texts in failures.items():
        lines += ["", f"### {name}", "", "```", "\n\n".join(texts), "```"]
    return lines


def render(
    fuzz: FuzzResults,
    blocking: FuzzResults,
    ops: dict[str, str],
    features: list[Feature],
    smoke_lines: list[str],
    *,
    required_smoke: tuple[str, ...] = REQUIRED_SMOKE,
    setup_problems: tuple[str, ...] = (),
) -> tuple[str, bool]:
    smoke_ok = sum(1 for line in smoke_lines if line.startswith("ok "))
    missing_smoke = [check for check in required_smoke if f"ok {check}" not in smoke_lines]
    smoke_pass = bool(smoke_lines) and smoke_ok == len(smoke_lines) and not missing_smoke
    blocking_failures = {name: texts for name, (status, texts) in blocking.items() if status == "fail"}
    unfuzzed = sorted(op for op in ops.values() if blocking.get(op, ("not run", []))[0] != "pass")
    blocking_pass = bool(blocking) and not blocking_failures and not unfuzzed
    advisory = {name: texts for name, (status, texts) in fuzz.items() if status == "fail"}
    overall = smoke_pass and blocking_pass and not setup_problems
    if not blocking:
        blocking_text = "not run"
    elif blocking_failures:
        blocking_text = f"fail ({len(blocking_failures)})"
    elif unfuzzed:
        blocking_text = f"incomplete ({len(unfuzzed)} operations not fuzzed or skipped)"
    else:
        blocking_text = "pass"
    lines = [
        "# Verification report",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Overall | {'pass' if overall else 'fail'} |",
        f"| Smoke | {'pass' if smoke_pass else 'fail'} ({smoke_ok}/{len(smoke_lines)}) |",
        f"| Blocking 5xx | {blocking_text} |",
        f"| Fuzz operations | {len(fuzz)} |",
        f"| Advisory fuzz failures | {len(advisory)} |",
        f"| Spec and fuzz config | {f'fail ({len(setup_problems)})' if setup_problems else 'pass'} |",
        "",
        "## Features",
        "",
        "| Feature | Operations | Fuzz | Proven by |",
        "|---|---|---|---|",
    ]
    for feature in features:
        proven = "<br>".join(feature["provenBy"])
        status = feature_status(fuzz, ops, feature)
        lines.append(f"| {feature['name']} | {', '.join(feature['operations'])} | {status} | {proven} |")
    if setup_problems:
        lines += ["", "## Spec and fuzz config problems", "", *[f"- {p}" for p in setup_problems]]
    lines += ["", "## Smoke", "", *[f"- {line}" for line in smoke_lines]]
    lines += [f"- MISSING required check: {check}" for check in missing_smoke]
    if unfuzzed:
        lines += ["", "## Operations the blocking run did not pass", "", *[f"- {op}" for op in unfuzzed]]
    if blocking_failures:
        lines += _section("Blocking failures (5xx)", blocking_failures)
    if advisory:
        lines += _section("Advisory fuzz failures", advisory)
    return "\n".join(lines) + "\n", overall
