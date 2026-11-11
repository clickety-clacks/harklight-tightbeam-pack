#!/usr/bin/env python3
"""Create a versioned public pack release after a reviewed main-branch merge."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from privacy_check import private_terms_from_environment, scan_repository


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def _run(args: list[str]) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("release preparation failed")
    return result.stdout.strip()


def _version(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", value.strip())
    return tuple(map(int, match.groups())) if match else None


def _previous_version() -> str | None:
    result = subprocess.run(
        ["git", "show", "HEAD^:VERSION"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _release_notes(version: str) -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^## v" + re.escape(version) + r"\s*\n(.*?)(?=^## v|\Z)",
        changelog,
    )
    if not match or not match.group(1).strip():
        raise RuntimeError("the versioned changelog entry is missing")
    return f"Harklight for Tightbeam v{version}\n\n{match.group(1).strip()}\n"


def _build_assets(version: str) -> tuple[Path, Path, Path]:
    pack_dir = ROOT / "pack"
    required = [
        pack_dir / "skill" / "harklight-agent" / "SKILL.md",
        pack_dir / "guidance.md",
        pack_dir / "elections.json",
    ]
    if any(not path.is_file() for path in required):
        raise RuntimeError("the generated pack is incomplete")
    DIST.mkdir(exist_ok=True)
    stage = DIST / f"harklight-pack-v{version}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    shutil.copy2(ROOT / "VERSION", stage / "VERSION")
    shutil.copytree(pack_dir, stage / "pack")

    archive_path = DIST / f"harklight-pack-v{version}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(stage, arcname=stage.name)

    script_path = DIST / "harklight-pack.py"
    shutil.copy2(ROOT / "bin" / "harklight_pack.py", script_path)
    sums_path = DIST / "SHA256SUMS"
    names = (archive_path, script_path)
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in names
    ]
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return archive_path, script_path, sums_path


def main() -> int:
    try:
        current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        parsed = _version(current)
        previous = _previous_version()
        previous_parsed = _version(previous) if previous else None
        if parsed is None or current == previous:
            print("no versioned pack release is required")
            return 0
        if previous_parsed is not None and parsed <= previous_parsed:
            raise RuntimeError("the release version must increase")
        notes = _release_notes(current)
        terms = private_terms_from_environment()
        findings = scan_repository(
            ROOT, terms, extra_texts={"release notes": notes}
        )
        if findings:
            raise RuntimeError("privacy check failed before release publication")
        policy = json.loads((ROOT / "sync-policy.json").read_text(encoding="utf-8"))
        release_policy = policy.get("release_policy")
        if release_policy not in {"manual", "auto"}:
            raise RuntimeError("the configured release policy is not recognized")
        event_name = os.environ.get("GITHUB_EVENT_NAME")
        if event_name == "push" and release_policy != "auto":
            print("automatic release publication is disabled by policy")
            return 0
        if event_name not in {"push", "workflow_dispatch"}:
            raise RuntimeError("release publication requires a GitHub release event")
        branch = _run(["git", "branch", "--show-current"])
        if branch != "main":
            raise RuntimeError("release publication requires the main branch")
        target = os.environ.get("GITHUB_SHA") or _run(
            ["git", "rev-parse", "HEAD"]
        )
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", target):
            raise RuntimeError("the release target is not a commit SHA")
        archive, script, sums = _build_assets(current)
        tag = f"v{current}"
        title = f"Harklight for Tightbeam {tag}"
        _run(
            [
                "gh",
                "release",
                "create",
                tag,
                str(archive),
                str(script),
                str(sums),
                "--title",
                title,
                "--notes",
                notes,
                "--target",
                target,
            ]
        )
        print(f"published versioned pack release {tag}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"release refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
