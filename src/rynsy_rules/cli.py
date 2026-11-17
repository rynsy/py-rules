import argparse
import sys
from importlib.resources import files
from pathlib import Path

from rynsy_rules import features, report
from rynsy_rules.comments import check_paths, check_pyproject, nested_ruff_configs

CONFIG = Path(".ruff-rynsy.toml")


COMPOSITION_ROOT = '"src/*/main.py"'


def write_config() -> None:
    base = files("rynsy_rules").joinpath("base-ruff.toml").read_text(encoding="utf-8")
    lines: list[str] = []
    for line in base.splitlines():
        if line.startswith(COMPOSITION_ROOT):
            rest = line.removeprefix(COMPOSITION_ROOT)
            lines += [f'"{root.as_posix()}"{rest}' for root in sorted(Path("src").glob("*/main.py"))]
        else:
            lines.append(line)
    CONFIG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report(args: argparse.Namespace) -> int:
    smoke = args.smoke.read_text(encoding="utf-8").splitlines() if args.smoke.exists() else []
    ops, spec_problems = features.operations(args.openapi)
    text, overall = report.render(
        report.fuzz_results(args.junit),
        report.fuzz_results(args.blocking_junit),
        ops,
        features.load_features(args.features),
        [line for line in smoke if line.strip()],
        required_smoke=tuple(args.require_smoke),
        setup_problems=(
            *spec_problems,
            *report.config_problems(args.schemathesis_config, features.declared_statuses(args.openapi)),
        ),
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
    verify.add_argument(
        "--require-smoke",
        action="append",
        default=list(report.REQUIRED_SMOKE),
        help="a smoke check that must be present and ok (repeatable; the seal checks are always required)",
    )
    verify.add_argument("--features", type=Path, default=Path("features.json"))
    verify.add_argument(
        "--schemathesis-config",
        type=Path,
        default=Path("schemathesis.toml"),
        help="checked, not applied: it may only let named operations answer 502-504",
    )
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
    missing = [p for p in args.paths if not p.exists()]
    if missing:
        sys.stdout.writelines(f"{p}: no such file or directory\n" for p in missing)
        return 2
    findings = check_paths(args.paths)
    pyproject = Path("pyproject.toml")
    if pyproject.is_file():
        findings.extend(check_pyproject(pyproject))
    findings.extend(nested_ruff_configs())
    for finding in findings:
        sys.stdout.write(f"{finding}\n")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
