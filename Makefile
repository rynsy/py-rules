# `make check` is the whole gate, locally and in CI. The package lints itself with its own rules.
.PHONY: check sync format lint types test

check: format lint types test

sync:
	uv sync --locked
	uv run rynsy-rules config

format: sync
	uv run ruff format --check .

lint: sync
	uv run ruff check .
	uv run rynsy-rules check .

types: sync
	uv run mypy

test: sync
	uv run pytest
