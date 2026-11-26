"""Check release claims against executed compatibility cases and the last tag."""

import ast
import re
import subprocess
import sys
from pathlib import Path


VERSION_PATTERN = r"[0-9]+\.[0-9]+\.[0-9]+(?:\+[A-Za-z0-9.-]+)?"


def tested_versions(root: Path) -> tuple[str, ...]:
    """Run every exact-version runtime case. Fixture unit tests do not count."""
    versions = []
    for case in sorted((root / "tests" / "runtime").glob("*.py")):
        if not re.fullmatch(VERSION_PATTERN, case.stem):
            raise RuntimeError(f"runtime case must name an exact Tightbeam version: {case.name}")
        result = subprocess.run(
            [sys.executable, str(case), str(root), case.stem], cwd=root, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"Tightbeam {case.stem} compatibility test failed")
        versions.append(case.stem)
    return tuple(versions)


def installer_contract(source: str) -> set[str]:
    """Read literal installer actions, flags, environment keys and output prefixes."""
    contract = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr == "add_argument":
            contract.update(
                f"flag {arg.value}" for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                and arg.value.startswith("-")
            )
            for keyword in node.keywords:
                if keyword.arg == "choices" and isinstance(keyword.value, (ast.Tuple, ast.List)):
                    contract.update(
                        f"action {item.value}" for item in keyword.value.elts
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)
                    )
        if isinstance(function, ast.Name) and function.id == "print" and node.args:
            value = node.args[0]
            if isinstance(value, ast.JoinedStr):
                value = value.values[0]
            if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
                contract.add(f"output {value.value.splitlines()[0]}")
        if isinstance(function, ast.Attribute) and function.attr in {"get", "pop"} and node.args:
            if ast.unparse(function.value) == "os.environ":
                key = node.args[0]
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    contract.add(f"environment key {key.value}")
    return contract


def breaking_signals(root: Path, previous: str, previous_notes: str, verified: tuple[str, ...]) -> list[str]:
    path = "bin/harklight_pack.py"
    baseline = subprocess.run(
        ["git", "show", f"refs/tags/v{previous}:{path}"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    if baseline.returncode != 0:
        raise RuntimeError("cannot read the previous published installer")
    current = (root / path).read_text(encoding="utf-8")
    removed = installer_contract(baseline.stdout) - installer_contract(current)
    prior = re.search(r"^Compatible with Tightbeam: (.*)$", previous_notes, re.M)
    if prior:
        removed.update(
            f"verified Tightbeam version {version.strip()}"
            for version in prior.group(1).split(",")
            if re.fullmatch(VERSION_PATTERN, version.strip()) and version.strip() not in verified
        )
    return sorted(removed)
