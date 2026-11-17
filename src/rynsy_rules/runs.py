import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def _node_id(case: ET.Element) -> str:
    file = case.get("file", "")
    module = file.removesuffix(".py").replace("/", ".")
    classname = case.get("classname", "")
    owner = classname[len(module) + 1 :] if classname.startswith(module + ".") else ""
    return "::".join(part for part in (file, owner, case.get("name", "")) if part)


def _outcome(case: ET.Element) -> str:
    tags = {child.tag for child in case}
    if tags & {"failure", "error"}:
        return "failed"
    return "skipped" if "skipped" in tags else "passed"


def unpassed(root: Path, node_ids: list[str]) -> dict[str, str]:
    """Run the proofs with pytest; map each proof that did not pass to what happened instead."""
    if not node_ids:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "proofs.xml"
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "-o",
                "junit_family=xunit1",
                f"--junitxml={junit}",
                *node_ids,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        outcomes: dict[str, list[str]] = {}
        if junit.exists():
            for case in ET.parse(junit).getroot().iter("testcase"):
                outcomes.setdefault(_node_id(case), []).append(_outcome(case))
    tail = done.stdout.strip().splitlines()[-1:] or [f"pytest exited {done.returncode}"]
    found: dict[str, str] = {}
    for node_id in node_ids:
        results = [
            o
            for key, found_outcomes in outcomes.items()
            if key == node_id or key.startswith(node_id + "[")
            for o in found_outcomes
        ]
        if not results:
            found[node_id] = f"did not run when collected by pytest ({tail[0]})"
        elif set(results) != {"passed"}:
            found[node_id] = f"did not pass when run ({', '.join(sorted(set(results)))})"
    return found
