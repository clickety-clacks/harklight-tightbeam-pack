#!/usr/bin/env python3
"""Apply or update the Harklight for Tightbeam pack."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


REPOSITORY = "clickety-clacks/harklight-tightbeam-pack"
SKILL_RELATIVE = Path("skill/harklight-agent/SKILL.md")
GUIDANCE_RELATIVE = Path("guidance.md")
ELECTIONS_RELATIVE = Path("elections.json")
GUIDANCE_BEGIN_PREFIX = "<!-- BEGIN HARKLIGHT FOR TIGHTBEAM v"
GUIDANCE_END = "<!-- END HARKLIGHT FOR TIGHTBEAM -->"
SKILL_MARKER = "<!-- HARKLIGHT_PACK_MANAGED -->"
ELECTION_MARKER = "# HARKLIGHT_PACK_ELECTED"
SKILL_NAME = "harklight-agent"


class ApplyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pack:
    version: str
    skill: str
    guidance: str
    roles: tuple[str, ...]


def _local_root() -> Path | None:
    source = Path(__file__)
    if str(source) == "<stdin>" or not source.exists():
        return None
    candidate = source.resolve().parents[1]
    return candidate if (candidate / "pack").is_dir() else None


def _semver(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?([0-9]+)\.([0-9]+)\.([0-9]+)", value.strip())
    return tuple(map(int, match.groups())) if match else None


def _request(url: str, accept: str = "application/vnd.github+json") -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "harklight-tightbeam-pack",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except Exception as error:
        raise ApplyError("the public pack release could not be downloaded") from error


def _load_pack_directory(directory: Path) -> Pack:
    version = (directory / "VERSION").read_text(encoding="utf-8").strip()
    skill = (directory / "pack" / SKILL_RELATIVE).read_text(encoding="utf-8")
    guidance = (directory / "pack" / GUIDANCE_RELATIVE).read_text(encoding="utf-8")
    elections = json.loads(
        (directory / "pack" / ELECTIONS_RELATIVE).read_text(encoding="utf-8")
    )
    roles = elections.get("roles")
    if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
        raise ApplyError("the downloaded pack election list is malformed")
    if SKILL_MARKER not in skill:
        raise ApplyError("the downloaded pack skill is missing its ownership marker")
    if not guidance.strip():
        raise ApplyError("the downloaded pack guidance is empty")
    return Pack(version, skill, guidance, tuple(sorted(set(roles))))


def _download_latest_pack() -> Pack:
    api_url = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
    release = json.loads(_request(api_url))
    tag = release.get("tag_name")
    version = _semver(str(tag or ""))
    if release.get("draft") or release.get("prerelease") or version is None:
        raise ApplyError("the latest public release is not a stable version")
    assets = {asset.get("name"): asset for asset in release.get("assets", [])}
    archive_name = f"harklight-pack-{tag}.tar.gz"
    if archive_name not in assets or "SHA256SUMS" not in assets:
        raise ApplyError("the latest public release is missing its pack archive")
    sums = _request(assets["SHA256SUMS"]["browser_download_url"]).decode("utf-8")
    expected = None
    for line in sums.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].lstrip("* ") == archive_name:
            expected = parts[0].lower()
            break
    if not expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ApplyError("the release archive has no valid checksum")
    archive_bytes = _request(assets[archive_name]["browser_download_url"])
    if hashlib.sha256(archive_bytes).hexdigest() != expected:
        raise ApplyError("the release archive checksum does not match")

    allowed: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            for member in archive.getmembers():
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts or not member.isfile():
                    continue
                if name.name == "VERSION" or "pack" in name.parts:
                    stream = archive.extractfile(member)
                    if stream is not None:
                        allowed[name.as_posix()] = stream.read()
    except (tarfile.TarError, OSError) as error:
        raise ApplyError("the release archive could not be read") from error

    version_candidates = [data.decode("utf-8").strip() for name, data in allowed.items() if name.endswith("/VERSION") or name == "VERSION"]
    if version_candidates != [str(tag).removeprefix("v")]:
        raise ApplyError("the release archive version does not match its tag")

    def find_suffix(suffix: str) -> str:
        matches = [data for name, data in allowed.items() if name.endswith(suffix)]
        if len(matches) != 1:
            raise ApplyError("the release archive is missing an expected pack file")
        try:
            return matches[0].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ApplyError("the release pack contains invalid text") from error

    skill = find_suffix("/pack/skill/harklight-agent/SKILL.md")
    guidance = find_suffix("/pack/guidance.md")
    elections_text = find_suffix("/pack/elections.json")
    elections = json.loads(elections_text)
    roles = elections.get("roles")
    if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
        raise ApplyError("the downloaded pack election list is malformed")
    if SKILL_MARKER not in skill or not guidance.strip():
        raise ApplyError("the downloaded pack content is incomplete")
    return Pack(str(tag).removeprefix("v"), skill, guidance, tuple(sorted(set(roles))))


def _selected_pack(action: str, source_dir: Path | None) -> Pack:
    if source_dir is not None:
        return _load_pack_directory(source_dir.resolve())
    local = _local_root()
    if action == "apply" and local is not None:
        return _load_pack_directory(local)
    if action == "update" or local is None:
        return _download_latest_pack()
    return _load_pack_directory(local)


def _identity_root() -> tuple[Path, Path]:
    base_raw = (
        os.environ.get("TIGHTBEAM_BASE_DIR")
        or os.environ.get("TIGHTBEAM_HOME")
        or str(Path.home() / ".tightbeam")
    )
    base = Path(base_raw).expanduser().resolve()
    expected = (base / "identity").resolve()
    configured = os.environ.get("TIGHTBEAM_IDENTITY_DIR")
    identity = Path(configured).expanduser().resolve() if configured else expected
    if identity != expected:
        raise ApplyError("the identity directory must belong to the selected Tightbeam base")
    if not (identity / "archetypes").is_dir() or not (identity / "guidance").is_dir():
        raise ApplyError("the selected Tightbeam identity directory is unavailable")
    return base, identity


def _guidance_block(content: str, version: str) -> str:
    return (
        f"{GUIDANCE_BEGIN_PREFIX}{version} -->\n"
        + content.strip()
        + "\n"
        + GUIDANCE_END
    )


def _replace_guidance(existing: str, block: str) -> str:
    begin_lines = [
        match
        for match in re.finditer(
            r"(?m)^<!-- BEGIN HARKLIGHT FOR TIGHTBEAM v[^>]+ -->$",
            existing,
        )
    ]
    end_lines = list(re.finditer(r"(?m)^" + re.escape(GUIDANCE_END) + r"$", existing))
    if len(begin_lines) != len(end_lines) or len(begin_lines) > 1:
        raise ApplyError("the marked guidance section is incomplete or ambiguous")
    if not begin_lines:
        if "HARKLIGHT FOR TIGHTBEAM" in existing:
            raise ApplyError("an unmarked Harklight pack section already exists")
        separator = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        return existing + separator + block + "\n"
    begin = begin_lines[0]
    end = end_lines[0]
    if begin.start() > end.start():
        raise ApplyError("the marked guidance section is out of order")
    end_after = end.end()
    if end_after < len(existing) and existing[end_after : end_after + 1] == "\n":
        end_after += 1
    if begin.group(0) + "\n" + existing[begin.end() : end.start()].strip() + "\n" + end.group(0) == block:
        return existing
    return existing[: begin.start()] + block + "\n" + existing[end_after:]


def _skills_assignment(manifest: str) -> tuple[int, int, int, list[str]]:
    matches = list(re.finditer(r"(?m)^skills\s*=\s*\[", manifest))
    if len(matches) != 1:
        raise ApplyError("an archetype has an unsupported skills field")
    match = matches[0]
    opening = manifest.find("[", match.start(), match.end())
    quote = False
    escaped = False
    closing = -1
    for index in range(opening + 1, len(manifest)):
        char = manifest[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote:
            escaped = True
            continue
        if char == '"':
            quote = not quote
        elif char == "]" and not quote:
            closing = index
            break
    if closing < 0:
        raise ApplyError("an archetype skills array is incomplete")
    try:
        data = tomllib.loads(manifest)
    except tomllib.TOMLDecodeError as error:
        raise ApplyError("an archetype manifest is malformed") from error
    skills = data.get("skills")
    if not isinstance(skills, list) or any(not isinstance(item, str) for item in skills):
        raise ApplyError("an archetype skills field has an unsupported shape")
    return match.start(), opening, closing, skills


def _add_election(manifest: str) -> str:
    start, opening, closing, skills = _skills_assignment(manifest)
    if SKILL_NAME in skills:
        return manifest
    inner = manifest[opening + 1 : closing]
    if "\n" in inner:
        trimmed = inner.rstrip()
        comma = "" if not trimmed or trimmed.endswith(",") else ","
        replacement = trimmed + comma + '\n  "' + SKILL_NAME + '"'
        if inner.endswith("\n"):
            replacement += "\n"
    else:
        trimmed = inner.rstrip()
        if trimmed:
            replacement = trimmed + ', "' + SKILL_NAME + '"'
        else:
            replacement = '"' + SKILL_NAME + '"'
        if inner.endswith(" "):
            replacement += " "
    updated = manifest[: opening + 1] + replacement + manifest[closing:]
    line_start = updated.rfind("\n", 0, start) + 1
    return updated[:line_start] + ELECTION_MARKER + "\n" + updated[line_start:]


def _remove_election(manifest: str) -> str:
    start, opening, closing, skills = _skills_assignment(manifest)
    marker_start = manifest.rfind(ELECTION_MARKER, 0, start)
    if marker_start < 0 or manifest[marker_start + len(ELECTION_MARKER) : start].strip():
        return manifest
    if SKILL_NAME not in skills:
        line_end = manifest.find("\n", marker_start)
        return manifest[:marker_start] + (manifest[line_end + 1 :] if line_end >= 0 else "")
    inner = manifest[opening + 1 : closing]
    token = re.search(r'"' + re.escape(SKILL_NAME) + r'"', inner)
    if not token or len(re.findall(r'"' + re.escape(SKILL_NAME) + r'"', inner)) != 1:
        raise ApplyError("a pack-owned election has an unsupported format")
    left = token.start()
    right = token.end()
    before = left - 1
    after = right
    while before >= 0 and inner[before].isspace():
        before -= 1
    while after < len(inner) and inner[after].isspace():
        after += 1
    if after < len(inner) and inner[after] == ",":
        after += 1
    elif before >= 0 and inner[before] == ",":
        left = before
    new_inner = inner[:left] + inner[after:]
    updated = manifest[: opening + 1] + new_inner + manifest[closing:]
    marker_start = updated.rfind(ELECTION_MARKER, 0, start)
    marker_end = updated.find("\n", marker_start)
    if marker_end < 0:
        return updated[:marker_start]
    return updated[:marker_start] + updated[marker_end + 1 :]


def _toml_roles(identity: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted((identity / "archetypes").glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ApplyError("an installed archetype manifest cannot be read") from error
        name = data.get("name")
        if not isinstance(name, str) or name != path.stem:
            raise ApplyError("an installed archetype has an unexpected identity")
        result[name] = path
    return result


def _managed_guidance(identity: Path, pack: Pack) -> tuple[Path, str]:
    path = identity / "guidance" / "default.md"
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as error:
        raise ApplyError("the default guidance file cannot be read") from error
    return path, _replace_guidance(existing, _guidance_block(pack.guidance, pack.version))


def _planned_changes(identity: Path, pack: Pack) -> list[tuple[str, Path, str]]:
    changes: list[tuple[str, Path, str]] = []
    skill_path = identity / "skills" / SKILL_NAME / "SKILL.md"
    existing_skill = skill_path.read_text(encoding="utf-8") if skill_path.exists() else None
    if existing_skill is not None and SKILL_MARKER not in existing_skill and existing_skill != pack.skill:
        raise ApplyError("an organization-owned skill already uses the pack's skill name")
    if existing_skill != pack.skill:
        changes.append(("skill", skill_path, pack.skill))

    guidance_path, guidance = _managed_guidance(identity, pack)
    try:
        current_guidance = (
            guidance_path.read_text(encoding="utf-8") if guidance_path.exists() else ""
        )
    except OSError as error:
        raise ApplyError("the default guidance file cannot be read") from error
    if guidance != current_guidance:
        changes.append(("guidance", guidance_path, guidance))

    manifests = _toml_roles(identity)
    desired = set(pack.roles)
    for role in sorted(desired):
        path = manifests.get(role)
        if path is None:
            continue
        current = path.read_text(encoding="utf-8")
        updated = _add_election(current)
        if updated != current:
            changes.append((f"manifest:{role}", path, updated))
    for role, path in sorted(manifests.items()):
        if role in desired:
            continue
        current = path.read_text(encoding="utf-8")
        updated = _remove_election(current)
        if updated != current:
            changes.append((f"manifest:{role}", path, updated))
    return changes


def _apply(identity_root: Path, base_dir: Path, pack: Pack) -> None:
    changes = _planned_changes(identity_root, pack)
    if not changes:
        print(f"Harklight for Tightbeam v{pack.version} is already applied")
        return
    tightbeam = shutil.which(os.environ.get("TIGHTBEAM_CLI", "tightbeam"))
    if tightbeam is None:
        raise ApplyError("the Tightbeam CLI is not available")

    env = os.environ.copy()
    env["TIGHTBEAM_BASE_DIR"] = str(base_dir)
    env.pop("TIGHTBEAM_URL", None)
    env.pop("TIGHTBEAM_TOKEN", None)
    with tempfile.TemporaryDirectory(prefix="harklight-pack-") as temp:
        temp_root = Path(temp)
        for index, (kind, path, content) in enumerate(changes):
            staged_file = temp_root / f"{index}-{path.name}"
            staged_file.write_text(content, encoding="utf-8")
            command = [tightbeam, "identity", "edit"]
            if kind == "skill":
                command.extend(["default", "--skill", SKILL_NAME])
            elif kind == "guidance":
                command.append("default")
            else:
                role = kind.removeprefix("manifest:")
                command.extend([role, "--manifest"])
            command.extend(["--file", str(staged_file)])
            result = subprocess.run(
                command,
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise ApplyError(
                    "Tightbeam rejected an identity edit; completed earlier edits are safe to re-run"
                )
            print(f"applied {kind}")
    print(f"Harklight for Tightbeam v{pack.version} is applied")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("apply", "update"))
    parser.add_argument("--identity-dir", type=Path)
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()
    if args.identity_dir:
        os.environ["TIGHTBEAM_IDENTITY_DIR"] = str(args.identity_dir)
    try:
        pack = _selected_pack(args.action, args.source_dir)
        base_dir, identity = _identity_root()
        _apply(identity, base_dir, pack)
        return 0
    except (OSError, ValueError, ApplyError) as error:
        print(f"pack apply refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
