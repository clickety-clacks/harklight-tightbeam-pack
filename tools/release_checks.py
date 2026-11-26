"""Check release claims against executed compatibility cases and the last tag."""

import ast
import json
import re
import subprocess
from pathlib import Path


VERSION_PATTERN = r"[0-9]+\.[0-9]+\.[0-9]+(?:\+[A-Za-z0-9.-]+)?"


def installer_contract(source: str) -> set[str]:
    """Read literal installer actions, flags, environment keys and output prefixes."""
    tree = ast.parse(source)
    identity_constants = {
        "SKILL_MARKER", "ELECTION_MARKER", "SKILL_NAME",
        "GUIDANCE_BEGIN_PREFIX", "GUIDANCE_END",
    }
    contract = {
        f"{target.id} {node.value.value}"
        for node in tree.body if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in identity_constants
    }
    for node in ast.walk(tree):
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
    def previous_file(path: str) -> str:
        baseline = subprocess.run(
            ["git", "show", f"refs/tags/v{previous}:{path}"],
            cwd=root, capture_output=True, text=True, check=False,
        )
        if baseline.returncode != 0:
            raise RuntimeError(f"cannot read {path} from the previous published pack")
        return baseline.stdout

    installer = "bin/harklight_pack.py"
    current = (root / installer).read_text(encoding="utf-8")
    removed = installer_contract(previous_file(installer)) - installer_contract(current)
    elections = "pack/elections.json"
    old_roles = set(json.loads(previous_file(elections))["roles"])
    new_roles = set(json.loads((root / elections).read_text(encoding="utf-8"))["roles"])
    removed.update(f"pack election for {role}" for role in old_roles - new_roles)
    prior = re.search(r"^Compatible with Tightbeam: (.*)$", previous_notes, re.M)
    if prior:
        removed.update(
            f"verified Tightbeam version {version.strip()}"
            for version in prior.group(1).split(",")
            if re.fullmatch(VERSION_PATTERN, version.strip()) and version.strip() not in verified
        )
    return sorted(removed)
