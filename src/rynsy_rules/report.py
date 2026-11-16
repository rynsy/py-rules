import xml.etree.ElementTree as ET
from pathlib import Path

from rynsy_rules.features import Feature

FuzzResults = dict[str, tuple[str, list[str]]]


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
) -> tuple[str, bool]:
    smoke_ok = sum(1 for line in smoke_lines if line.startswith("ok "))
    smoke_pass = bool(smoke_lines) and smoke_ok == len(smoke_lines)
    blocking_failures = {name: texts for name, (status, texts) in blocking.items() if status == "fail"}
    blocking_pass = bool(blocking) and not blocking_failures
    advisory = {name: texts for name, (status, texts) in fuzz.items() if status == "fail"}
    overall = smoke_pass and blocking_pass
    if not blocking:
        blocking_text = "not run"
    elif blocking_failures:
        blocking_text = f"fail ({len(blocking_failures)})"
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
    lines += ["", "## Smoke", "", *[f"- {line}" for line in smoke_lines]]
    if blocking_failures:
        lines += _section("Blocking failures (5xx)", blocking_failures)
    if advisory:
        lines += _section("Advisory fuzz failures", advisory)
    return "\n".join(lines) + "\n", overall
