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
from release_checks import breaking_signals
from runtime_compat import tested_versions


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
    try:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    except FileNotFoundError:
        changelog = ""
    match = re.search(
        r"(?ms)^## v" + re.escape(version) + r"\s*\n(.*?)(?=^## v|\Z)",
        changelog,
    )
    if not match or not match.group(1).strip():
        return f"Harklight for Tightbeam v{version}\n"
    return f"Harklight for Tightbeam v{version}\n\n{match.group(1).strip()}\n"


def _validate_release_notes(
    notes: str, verified: tuple[str, ...], signals: list[str]
) -> str:
    expected = "Compatible with Tightbeam: " + (", ".join(verified) or "None verified.")
    declarations = re.findall(r"^Compatible with Tightbeam:.*$", notes, re.M)
    if declarations == ["Compatible with Tightbeam: From release tests."] and verified:
        notes = notes.replace(declarations[0], expected, 1)
    elif declarations != [expected]:
        raise RuntimeError(f"release notes must match executed runtime cases: {expected}")
    sections = re.split(r"(?m)^#{1,6}[ \t]+", notes)
    breaking = [
        body.strip()
        for heading, _, body in (section.partition("\n") for section in sections[1:])
        if heading.strip() == "Breaking changes"
    ]
    if len(breaking) != 1 or not breaking[0]:
        raise RuntimeError("release notes require one nonempty Breaking changes section")
    if signals:
        entries = [
            line.strip(" \t-+*`.")
            for line in breaking[0].splitlines()
            if line.strip()
        ]
        placeholder = r"(?i)^(?:none\b|nothing\b|no\s+(?:breaking\b|changes\b)|n/?a\b|tbd\b)"
        if not entries or any(not entry or re.match(placeholder, entry) for entry in entries):
            raise RuntimeError("document detected breaking changes: " + ", ".join(signals))
    return notes


def _checked_release_notes(current: str, verified: tuple[str, ...]) -> str:
    verified = tuple(version.removeprefix("v") for version in verified)
    if len(verified) != 2 or len(set(verified)) != 2:
        raise RuntimeError("release requires two distinct verified Tightbeam versions")
    published = json.loads(_run(["gh", "release", "view", "--json", "tagName,body"]))
    tag = published["tagName"]
    if not tag.startswith("v") or _version(tag[1:]) is None:
        raise RuntimeError("the previous published pack tag is invalid")
    if tag == f"v{current}":
        raise RuntimeError("this pack version is already published")
    signals = breaking_signals(ROOT, tag[1:], published["body"], verified)
    if signals:
        print("Breaking change signals: " + ", ".join(signals))
    return _validate_release_notes(_release_notes(current), verified, signals)


def _preview_release_notes(result_path: Path) -> int:
    try:
        current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if current == _previous_version():
            print("no versioned pack release is required")
            return 0
        result = json.loads(result_path.read_text(encoding="utf-8"))
        _checked_release_notes(current, tuple(result["compatible_with_tightbeam"]))
        return 0
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        print(f"release notes check refused: {error}", file=sys.stderr)
        return 1


def _require_breaking_changes_review(target: str) -> None:
    endpoint = "repos/{owner}/{repo}"
    pulls = json.loads(_run(["gh", "api", f"{endpoint}/commits/{target}/pulls"]))
    matching = [
        pull for pull in pulls
        if pull["merged_at"] and pull["merge_commit_sha"] == target
        and pull["base"]["ref"] == "main"
    ]
    if len(matching) != 1:
        raise RuntimeError("the release commit must come from one merged main pull request")
    pull = matching[0]
    head = pull["head"]["sha"]
    number = pull["number"]
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", head):
        raise RuntimeError("the reviewed PR head is not a commit SHA")
    _run(["git", "fetch", "--no-tags", "origin", head])
    for path in ("VERSION", "CHANGELOG.md"):
        reviewed = _run(["git", "rev-parse", f"{head}:{path}"])
        released = _run(["git", "rev-parse", f"{target}:{path}"])
        if reviewed != released:
            raise RuntimeError("the released version and changelog must match the reviewed PR")

    pages = json.loads(_run([
        "gh", "api", "--paginate", "--slurp",
        f"{endpoint}/pulls/{number}/reviews?per_page=100",
    ]))
    latest = {}
    for review in sorted((review for page in pages for review in page), key=lambda row: row["id"]):
        if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[review["user"]["id"]] = review
    if not any(
        review["state"] == "APPROVED"
        and review["commit_id"] == head
        and review["user"]["id"] != pull["user"]["id"]
        and review["author_association"] in {"OWNER", "MEMBER", "COLLABORATOR"}
        and "Breaking changes confirmed." in (review.get("body") or "").splitlines()
        for review in latest.values()
    ):
        raise RuntimeError(
            "release requires an independent PR approval on its final head "
            "containing the line 'Breaking changes confirmed.'"
        )


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
        if parsed is None or current == previous:
            print("no versioned pack release is required")
            return 0
        terms = private_terms_from_environment()
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
        _require_breaking_changes_review(target)
        notes = _checked_release_notes(current, tested_versions(ROOT))
        if scan_repository(ROOT, terms, extra_texts={"release notes": notes}):
            raise RuntimeError("privacy check failed before release publication")
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
    if len(sys.argv) == 3 and sys.argv[1] == "--preview":
        raise SystemExit(_preview_release_notes(Path(sys.argv[2])))
    raise SystemExit(main())
