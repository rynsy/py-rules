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
	uv run rynsy-rules check src tests scripts
```

The config is written at the repository root because ruff resolves `per-file-ignores` globs relative to the file that declares them.

## What it sets

- `base-ruff.toml` (not `ruff.toml`, which ruff would apply to the package folder itself): every ruff rule on (`ALL`), minus the ones switched off on purpose; test, script and composition-root (`main.py`) exemptions; banned APIs.
- `rynsy-rules check`: the `RYP` rules, which ruff has no rule for.

## Verification commands

The same evidence for every service, so a PR is reviewed by reading `verify/report.md`, not the diff line by line.

- `rynsy-rules features [--openapi openapi/openapi.json] [--features features.json]`: every OpenAPI operation belongs to a feature, every feature names at least one proving test as a pytest node id (`tests/unit/test_x.py::test_y`), and each such test exists and is not skipped or xfail. Runs in `make check`.
- `rynsy-rules report --junit verify/fuzz.xml --blocking-junit verify/fuzz-5xx.xml --smoke verify/smoke.txt --out verify/report.md`: the report. Exits 1 unless smoke and the blocking (no 5xx) fuzz run both pass. Advisory fuzz failures are listed but do not fail it.

`features.json`:

```json
[{"name": "Start a sync", "operations": ["startSync"], "provenBy": ["tests/integration/test_api.py::test_start_sync_publishes"]}]
```

## Rules ledger

| ID | Forbids | Fix | Came from |
|---|---|---|---|
| RYP001 | `#` comments, except `# TODO(#<issue>)`, `# ponytail: <ceiling>` and a shebang. | Fix the root cause, or say it in a name, a type or a test; or open an issue. | 2026-11-16, carried from Rynsy.DotNet.Rules RYN0001: agents write comments to justify workarounds, and the next agent copies them (Lauren Tan, "All Code Is Slop") |
| RYP002 | Inline suppressions (`# noqa`, `# type: ignore`, `# pragma:`, `# fmt: off/on/skip`, `# pyright:`, `# mypy:`) without `TODO(#<issue>)` on the line. | Fix the finding. A permanent, reviewed exception goes in `extend-per-file-ignores`, where review sees it. | 2026-11-16, carried from RYN0002: a silent suppression is the same escape hatch as a justifying comment |
| TID251 (banned) | `time.sleep`, `asyncio.sleep` outside tests. | Await the event, or use the retry policy. | 2026-11-16, from RS0030 in the .NET rules: a delay hides a race |
| TID251 (banned) | `datetime.now`, `utcnow`, `today`, `date.today`, `time.time` outside tests and `main.py` (which may also bind `0.0.0.0`, S104). | Inject a clock from the composition root; `time.monotonic` for durations. | 2026-11-16, from RS0030: time you cannot control makes tests flaky |
| ERA001 (off) | — | RYP001 already rejects commented-out code. | 2026-11-16 |

## Adding a rule

1. Name the mistake. Pick the cheapest check that makes it impossible: change the consumer's API or architecture; else a ruff rule or a `banned-api` entry in `base-ruff.toml`; else an `RYP` rule in `comments.py` (or a new module); else an import-linter contract in the consumer.
2. Write the failing case first, in `tests/`.
3. Implement, `make check`, add the ledger row, open a PR. Release by tagging `vX.Y.Z` on `main`.
