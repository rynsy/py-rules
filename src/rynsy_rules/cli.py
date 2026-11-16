import argparse
import sys
from importlib.resources import files
from pathlib import Path

from rynsy_rules.comments import check_paths

CONFIG = Path(".ruff-rynsy.toml")


def write_config() -> None:
    CONFIG.write_text(
        files("rynsy_rules").joinpath("ruff.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rynsy-rules")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "config", help="write .ruff-rynsy.toml (gitignored) for pyproject's [tool.ruff] extend"
    )
    check = commands.add_parser("check", help="RYP001 comments and RYP002 suppressions")
    check.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)

    if args.command == "config":
        write_config()
        return 0
    findings = check_paths([p for p in args.paths if p.exists()])
    for finding in findings:
        sys.stdout.write(f"{finding}\n")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
