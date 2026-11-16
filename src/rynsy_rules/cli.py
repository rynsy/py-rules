import argparse
import sys
from importlib.resources import files
from pathlib import Path

from rynsy_rules import features, report
from rynsy_rules.comments import check_paths

CONFIG = Path(".ruff-rynsy.toml")


def write_config() -> None:
    CONFIG.write_text(
        files("rynsy_rules").joinpath("base-ruff.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )


def write_report(args: argparse.Namespace) -> int:
    smoke = args.smoke.read_text(encoding="utf-8").splitlines() if args.smoke.exists() else []
    text, overall = report.render(
        report.fuzz_results(args.junit),
        report.fuzz_results(args.blocking_junit),
        features.operation_ids(args.openapi),
        features.load_features(args.features),
        [line for line in smoke if line.strip()],
    )
    args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if overall else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rynsy-rules")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "config", help="write .ruff-rynsy.toml (gitignored) for pyproject's [tool.ruff] extend"
    )
    check = commands.add_parser("check", help="RYP001 comments and RYP002 suppressions")
    check.add_argument("paths", nargs="+", type=Path)
    feature_map = commands.add_parser(
        "features", help="each operation has a feature; each proof is a live test"
    )
    feature_map.add_argument("--openapi", type=Path, default=Path("openapi/openapi.json"))
    feature_map.add_argument("--features", type=Path, default=Path("features.json"))
    verify = commands.add_parser("report", help="write verify/report.md from smoke and Schemathesis results")
    for flag in ("--junit", "--blocking-junit", "--smoke", "--out"):
        verify.add_argument(flag, type=Path, required=True)
    verify.add_argument("--openapi", type=Path, default=Path("openapi/openapi.json"))
    verify.add_argument("--features", type=Path, default=Path("features.json"))
    args = parser.parse_args(argv)

    if args.command == "config":
        write_config()
        return 0
    if args.command == "features":
        found = list(features.problems(Path(), args.openapi, args.features))
        sys.stdout.writelines(f"{line}\n" for line in found)
        return 1 if found else 0
    if args.command == "report":
        return write_report(args)
    findings = check_paths([p for p in args.paths if p.exists()])
    for finding in findings:
        sys.stdout.write(f"{finding}\n")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
