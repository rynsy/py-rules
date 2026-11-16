# py-rules

`rynsy-py-rules`: the shared lint rules for every Python service built from `python-service-template`. A rule added here reaches every repo through a Renovate PR, and that PR's `make check` shows what the new rule breaks.

The idea: whenever an agent (or a person) gets something wrong, the correction becomes a rule here, not a line in AGENTS.md. A rule is enforced; a sentence in a prompt is not.

## Use it

`pyproject.toml`:

```toml
[dependency-groups]
dev = ["rynsy-py-rules"]

[tool.uv.sources]
rynsy-py-rules = { git = "https://github.com/rynsy/py-rules", tag = "v0.1.0" }

[tool.ruff]
extend = ".ruff-rynsy.toml"
src = ["src", "tests"]

[tool.ruff.lint.extend-per-file-ignores]
# repo-specific, reviewed exceptions only
```

`Makefile`:

```make
sync:
	uv sync --locked
	uv run rynsy-rules config        # writes .ruff-rynsy.toml (add it to .gitignore)

lint: sync
	uv run ruff check .
	uv run rynsy-rules check .
```

The config is written at the repository root because ruff resolves `per-file-ignores` globs relative to the file that declares them.

## What it sets

- `base-ruff.toml` (not `ruff.toml`, which ruff would apply to the package folder itself): every ruff rule on (`ALL`), minus the ones switched off on purpose; test, script and composition-root (`main.py`) exemptions; banned APIs.
- `rynsy-rules check`: the `RYP` rules, which ruff has no rule for.

## Verification commands

The same evidence for every service, so a PR is reviewed by reading `verify/report.md`, not the diff line by line.

- `rynsy-rules features [--openapi openapi/openapi.json] [--features features.json]`: every OpenAPI operation has a unique `operationId` and belongs to a feature; every feature names at least one proving test as a pytest node id (`tests/unit/test_x.py::test_y`, in a `test_*.py` or `*_test.py` file); each such test exists, asserts something (`assert`, `pytest.raises`, an `assert*` call) and is not skipped or xfail by any route (decorator, alias, class mark, module `pytestmark`, `pytest.skip()` in the body). Parametrize ids are not checked. Runs in `make check` and CI.
- `rynsy-rules report --junit verify/fuzz.xml --blocking-junit verify/fuzz-5xx.xml --smoke verify/smoke.txt --out verify/report.md`: the report. Exits 1 unless every smoke check passed, the two seal checks are among them (`the service cannot reach the internet`, `only the gateway is outside the sealed network`; add more with `--require-smoke`), and the blocking (no 5xx) fuzz run passed every OpenAPI operation (a skipped or missing operation is not a pass). Advisory fuzz failures are listed but do not fail it. It also fails when the OpenAPI document has an operation with no `operationId` or an id used twice, or when `schemathesis.toml` (`--schemathesis-config`, read but not applied) holds anything but `[[operations]]` tables that name operations by `include-operation-id` and let them answer 502, 503 or 504 through `checks.not_a_server_error.expected-statuses`. A config that sets the base URL, turns a check off or allows 500 is how a red run turns green.

`features.json`:

```json
[{"name": "Start a sync", "operations": ["startSync"], "provenBy": ["tests/integration/test_api.py::test_start_sync_publishes"]}]
```

## Rules ledger

| ID | Forbids | Fix | Came from |
|---|---|---|---|
| RYP001 | `#` comments, except `# TODO(#<issue>)` (issue ≥ 1), `# ponytail: <ceiling>` (at most two continuation lines directly below, at the same indent) and a shebang. | Fix the root cause, or say it in a name, a type or a test; or open an issue. | 2026-11-16, carried from Rynsy.DotNet.Rules RYN0001: agents write comments to justify workarounds, and the next agent copies them (Lauren Tan, "All Code Is Slop") |
| RYP002 | Inline suppressions in any case (`# noqa`, `# type: ignore`, `# pragma:`, `# fmt: off/on/skip`, `# pyright:`, `# mypy:`, `# ruff:`) without `TODO(#<issue>)` on the line. | Fix the finding. A permanent, reviewed exception goes in `extend-per-file-ignores`, where review sees it. | 2026-11-16, carried from RYN0002: a silent suppression is the same escape hatch as a justifying comment |
| RYP003 | A bare string statement anywhere but a module, class or function docstring position. | Delete it, or make it a docstring. | 2026-11-16, review: a string literal is a comment the comment rule could not see |
| RYP004 | A pyproject `[tool.ruff]` ignore or per-file-ignore that exempts `TID251`. | Move the clock or the wait to the composition root; or change the ban here. | 2026-11-16, review: any repo could switch the bans off for `src/**` |
| TID251 (banned) | `time.sleep`, `asyncio.sleep` outside `tests/` and `src/<pkg>/main.py`. | Await the event, or use the retry policy. | 2026-11-16, from RS0030 in the .NET rules: a delay hides a race |
| TID251 (banned) | `datetime.now`, `utcnow`, `today`, `date.today`, `time.time`, `time.time_ns`, `time.localtime` outside `tests/` and `src/<pkg>/main.py` (which may also bind `0.0.0.0`, S104). `rynsy-rules config` writes the exact `src/<pkg>/main.py` paths: ruff's `*` crosses `/`, so a pattern would also exempt any nested `main.py`. | Inject a clock from the composition root; `time.monotonic` for durations. | 2026-11-16, from RS0030: time you cannot control makes tests flaky |
| ERA001 (off) | — | RYP001 already rejects commented-out code. | 2026-11-16 |

## Adding a rule

1. Name the mistake. Pick the cheapest check that makes it impossible: change the consumer's API or architecture; else a ruff rule or a `banned-api` entry in `base-ruff.toml`; else an `RYP` rule in `comments.py` (or a new module); else an import-linter contract in the consumer.
2. Write the failing case first, in `tests/`.
3. Implement, `make check`, add the ledger row, open a PR. Release by tagging `vX.Y.Z` on `main`.
