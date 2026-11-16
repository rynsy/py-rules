from pathlib import Path

from rynsy_rules.features import Feature
from rynsy_rules.report import fuzz_results, render

JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite>
<testcase name="POST /v1/sync"><failure message="Server error">500 on {}</failure></testcase>
<testcase name="GET /v1/items"/>
<testcase name="GET /v1/other"><skipped/></testcase>
</testsuite></testsuites>
"""

SEALED = [
    "ok readyz",
    "ok the service cannot reach the internet",
    "ok only the gateway is outside the sealed network",
]
OPS = {"startSync": "POST /v1/sync", "listItems": "GET /v1/items"}
FEATURES: list[Feature] = [
    {"name": "Sync", "operations": ["startSync"], "provenBy": ["tests/a.py::test_a"]},
    {"name": "List", "operations": ["listItems"], "provenBy": ["tests/a.py::test_b"]},
]


def junit(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "fuzz.xml"
    path.write_text(text, encoding="utf-8")
    return path


def test_fuzz_results_read_pass_fail_and_skip(tmp_path: Path) -> None:
    results = fuzz_results(junit(tmp_path, JUNIT))
    assert {name: status for name, (status, _) in results.items()} == {
        "POST /v1/sync": "fail",
        "GET /v1/items": "pass",
        "GET /v1/other": "skipped",
    }
    assert "500 on {}" in results["POST /v1/sync"][1][0]


def test_missing_junit_means_not_run(tmp_path: Path) -> None:
    assert fuzz_results(tmp_path / "absent.xml") == {}


def test_a_5xx_fails_overall_and_is_shown(tmp_path: Path) -> None:
    results = fuzz_results(junit(tmp_path, JUNIT))
    text, overall = render(results, results, OPS, FEATURES, ["ok readyz"])
    assert not overall
    assert "| Overall | fail |" in text
    assert "| Blocking 5xx | fail (1) |" in text
    assert "| Sync | startSync | fail |" in text
    assert "| List | listItems | pass |" in text
    assert "## Blocking failures (5xx)" in text


def test_everything_green_passes(tmp_path: Path) -> None:
    both = fuzz_results(
        junit(
            tmp_path,
            '<testsuites><testcase name="GET /v1/items"/><testcase name="POST /v1/sync"/></testsuites>',
        )
    )
    text, overall = render(both, both, OPS, FEATURES, SEALED)
    assert overall, text
    assert "| Smoke | pass (3/3) |" in text


def test_no_blocking_run_or_failed_smoke_is_not_a_pass(tmp_path: Path) -> None:
    clean = fuzz_results(junit(tmp_path, '<testsuites><testcase name="GET /v1/items"/></testsuites>'))
    assert render(clean, {}, OPS, FEATURES, ["ok readyz"])[1] is False
    assert render(clean, clean, OPS, FEATURES, ["ok readyz", "FAIL egress blocked"])[1] is False
    assert render(clean, clean, OPS, FEATURES, [])[1] is False


def test_an_operation_the_blocking_run_skipped_or_missed_is_not_a_pass(tmp_path: Path) -> None:
    skipped = fuzz_results(
        junit(
            tmp_path,
            '<testsuites><testcase name="GET /v1/items"/>'
            '<testcase name="POST /v1/sync"><skipped/></testcase></testsuites>',
        )
    )
    text, overall = render(skipped, skipped, OPS, FEATURES, SEALED)
    assert not overall
    assert "incomplete (1 operations not fuzzed or skipped)" in text
    one = fuzz_results(junit(tmp_path, '<testsuites><testcase name="GET /v1/items"/></testsuites>'))
    assert render(one, one, OPS, FEATURES, SEALED)[1] is False


def test_a_smoke_without_the_seal_checks_is_not_a_pass(tmp_path: Path) -> None:
    both = fuzz_results(
        junit(
            tmp_path,
            '<testsuites><testcase name="GET /v1/items"/><testcase name="POST /v1/sync"/></testsuites>',
        )
    )
    text, overall = render(both, both, OPS, FEATURES, ["ok readyz"])
    assert not overall
    assert "MISSING required check: the service cannot reach the internet" in text
