#!/usr/bin/env python3
"""Find the Tightbeam releases this pack works with by applying it to each one.

The supported window is the current full Tightbeam release and the one before
it. For both, this downloads the official Linux package from the public
release, verifies it against the release's SHA256SUMS and provenance, boots its
gateway in a scratch organization, learns the engineering bundle, applies this
checkout's pack through the real identity-edit CLI, checks the result, and
applies it again to confirm nothing changes.

tested_versions() returns the exact release tags only after both cases pass.
Any discovery, download, checksum, setup or test failure raises
RuntimeCompatError instead of returning a shorter list.

This boots real gateways. It refuses to run outside CI unless
HARKLIGHT_PACK_RUNTIME_ISOLATED=1 confirms the machine has no Tightbeam
installation it could disturb.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


TIGHTBEAM_REPOSITORY = "clickety-clacks/tightbeam"
API_ROOT = "https://api.github.com"
BUNDLE = "agentic-engineering"
SKILL_NAME = "harklight-agent"
ELECTION_MARKER = "# HARKLIGHT_PACK_ELECTED"
GUIDANCE_BEGIN = "<!-- BEGIN HARKLIGHT FOR TIGHTBEAM v{version} -->"
GUIDANCE_END = "<!-- END HARKLIGHT FOR TIGHTBEAM -->"
PROCESS_NAME = "harklight-pack-runtime-compat"
WINDOW = 2
READY_TIMEOUT_SECONDS = 180
COMMAND_TIMEOUT_SECONDS = 180
TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:\+[0-9A-Za-z.-]+)?")


class RuntimeCompatError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    tag: str
    package: dict
    checksums: dict
    provenance: dict


# Discovery


def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    headers = {"Accept": accept, "User-Agent": "harklight-tightbeam-pack"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(API_ROOT + "/"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except (urllib.error.URLError, OSError) as error:
            last_error = error
            time.sleep(2 * (attempt + 1))
    raise RuntimeCompatError(f"download failed: {url}") from last_error


def _get_json(url: str):
    try:
        return json.loads(_get(url))
    except json.JSONDecodeError as error:
        raise RuntimeCompatError(f"unreadable response: {url}") from error


def _all_releases() -> list[dict]:
    releases: list[dict] = []
    for page in range(1, 51):
        batch = _get_json(
            f"{API_ROOT}/repos/{TIGHTBEAM_REPOSITORY}/releases?per_page=100&page={page}"
        )
        if not isinstance(batch, list):
            raise RuntimeCompatError("the Tightbeam release list has an unexpected shape")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
    raise RuntimeCompatError("the Tightbeam release list did not end")


def package_asset_name(tag: str) -> re.Pattern[str]:
    version = re.escape(tag.removeprefix("v").split("+", 1)[0])
    return re.compile(rf"tightbeam-{version}-linux-x86_64-[0-9a-f]{{7,40}}\.tgz")


def select_window(releases: list[dict], latest_tag: str) -> list[Release]:
    """Return the current and previous full releases, newest first.

    Drafts and prereleases are excluded. Order is by publication time, and the
    newest must be the release GitHub reports as latest. Anything ambiguous or
    incomplete is refused rather than skipped.
    """
    full = []
    for release in releases:
        if not isinstance(release, dict):
            raise RuntimeCompatError("a Tightbeam release entry has an unexpected shape")
        if release.get("draft") is not False or release.get("prerelease") is not False:
            continue
        tag = release.get("tag_name")
        published = release.get("published_at")
        if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
            raise RuntimeCompatError(f"a full Tightbeam release has an unexpected tag: {tag!r}")
        if not isinstance(published, str) or not published:
            raise RuntimeCompatError(f"Tightbeam release {tag} has no publication time")
        full.append((published, tag, release))
    full.sort(key=lambda item: item[0], reverse=True)
    if len(full) < WINDOW:
        raise RuntimeCompatError("fewer than two full Tightbeam releases are published")
    if len({published for published, _, _ in full[: WINDOW + 1]}) != len(full[: WINDOW + 1]):
        raise RuntimeCompatError("Tightbeam release publication order is ambiguous")
    if full[0][1] != latest_tag:
        raise RuntimeCompatError(
            f"newest full Tightbeam release {full[0][1]} is not the latest release {latest_tag}"
        )

    window = []
    for _, tag, release in full[:WINDOW]:
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise RuntimeCompatError(f"Tightbeam release {tag} has no asset list")
        by_name = {asset.get("name"): asset for asset in assets if isinstance(asset, dict)}
        pattern = package_asset_name(tag)
        packages = [asset for name, asset in by_name.items() if isinstance(name, str) and pattern.fullmatch(name)]
        if len(packages) != 1:
            raise RuntimeCompatError(f"Tightbeam release {tag} has no single Linux x86_64 package")
        for required in ("SHA256SUMS", "release-provenance.json"):
            if required not in by_name:
                raise RuntimeCompatError(f"Tightbeam release {tag} is missing {required}")
        window.append(
            Release(tag, packages[0], by_name["SHA256SUMS"], by_name["release-provenance.json"])
        )
    return window


def discover() -> list[Release]:
    latest = _get_json(f"{API_ROOT}/repos/{TIGHTBEAM_REPOSITORY}/releases/latest")
    latest_tag = latest.get("tag_name") if isinstance(latest, dict) else None
    if not isinstance(latest_tag, str):
        raise RuntimeCompatError("the latest Tightbeam release has no tag")
    return select_window(_all_releases(), latest_tag)


# Download and verification


def expected_digest(sums: str, name: str) -> str:
    matches = []
    for line in sums.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip().lstrip("*") == name:
            matches.append(parts[0].lower())
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0]):
        raise RuntimeCompatError(f"SHA256SUMS has no single valid entry for {name}")
    return matches[0]


def verify_provenance(provenance: object, tag: str, name: str) -> None:
    if not isinstance(provenance, dict):
        raise RuntimeCompatError(f"release provenance for {tag} is malformed")
    if provenance.get("repository") != TIGHTBEAM_REPOSITORY or provenance.get("tag") != tag:
        raise RuntimeCompatError(f"release provenance does not name {tag}")
    commit = provenance.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeCompatError(f"release provenance for {tag} has no source commit")
    short = name.removesuffix(".tgz").rsplit("-", 1)[-1]
    if not commit.startswith(short):
        raise RuntimeCompatError(f"package {name} was not built from the provenance commit")
    if name not in (provenance.get("assets") or []):
        raise RuntimeCompatError(f"release provenance for {tag} does not list {name}")


def _download_package(release: Release, directory: Path) -> Path:
    name = release.package["name"]
    sums = _get(release.checksums["browser_download_url"], "application/octet-stream")
    provenance_bytes = _get(release.provenance["browser_download_url"], "application/octet-stream")
    try:
        provenance = json.loads(provenance_bytes)
    except json.JSONDecodeError as error:
        raise RuntimeCompatError(f"release provenance for {release.tag} is unreadable") from error
    verify_provenance(provenance, release.tag, name)
    expected = expected_digest(sums.decode("utf-8", "replace"), name)
    data = _get(release.package["browser_download_url"], "application/octet-stream")
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeCompatError(f"package {name} does not match its published checksum")
    path = directory / name
    path.write_bytes(data)
    return path


def _extract(package: Path, destination: Path) -> Path:
    try:
        with tarfile.open(package, mode="r:gz") as archive:
            archive.extractall(destination, filter="tar")
    except (tarfile.TarError, OSError) as error:
        raise RuntimeCompatError(f"package {package.name} could not be unpacked") from error
    root = destination / "tightbeam"
    for executable in ("bin/tightbeam", "bin/tightbeam-gateway"):
        if not (root / executable).is_file():
            raise RuntimeCompatError(f"package {package.name} has no {executable}")
    return root


# Scratch organization


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


def _scratch_environment(scratch: Path, port: int, package_root: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("TIGHTBEAM_", "RELEASE_", "HARKLIGHT_"))
        and key not in {"GH_TOKEN", "GITHUB_TOKEN", "CREDENTIALS_DIRECTORY"}
    }
    home = scratch / "home"
    home.mkdir()
    env.update(
        {
            "HOME": str(home),
            "TIGHTBEAM_BASE_DIR": str(scratch / "base"),
            "TIGHTBEAM_PORT": str(port),
            "TIGHTBEAM_AS_PROCESS": PROCESS_NAME,
            "TIGHTBEAM_CLI": str(package_root / "bin" / "tightbeam"),
            "PATH": str(package_root / "bin") + os.pathsep + env.get("PATH", ""),
        }
    )
    return env


def _run(command: list[str], env: dict[str, str], cwd: Path, what: str) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeCompatError(f"{what} did not complete") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        raise RuntimeCompatError(f"{what} failed: " + " | ".join(detail))
    return result.stdout


def _log_tail(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return " | ".join(lines[-8:])


def _wait_ready(gateway: subprocess.Popen, env: dict[str, str], scratch: Path, log: Path) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    descriptor = Path(env["TIGHTBEAM_BASE_DIR"]) / "gateway.json"
    last = "gateway descriptor never appeared"
    while time.monotonic() < deadline:
        if gateway.poll() is not None:
            raise RuntimeCompatError(
                f"gateway exited during startup with {gateway.returncode}: {_log_tail(log)}"
            )
        if descriptor.is_file():
            try:
                _run([env["TIGHTBEAM_CLI"], "identity", "status"], env, scratch, "identity status")
                return
            except RuntimeCompatError as error:
                last = str(error)
        time.sleep(1)
    raise RuntimeCompatError(f"gateway did not become ready: {last}")


def _stop(gateway: subprocess.Popen, env: dict[str, str], package_root: Path, scratch: Path) -> None:
    if gateway.poll() is None:
        subprocess.run(
            [str(package_root / "bin" / "tightbeam-gateway"), "stop"],
            cwd=scratch,
            env=env,
            capture_output=True,
            timeout=60,
            check=False,
        )
        try:
            gateway.wait(timeout=60)
        except subprocess.TimeoutExpired:
            gateway.kill()
            gateway.wait(timeout=30)


# Pack checks


def _identity_digest(identity: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(identity.rglob("*")):
        if ".git" in path.relative_to(identity).parts or not path.is_file():
            continue
        digest.update(path.relative_to(identity).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def check_applied(identity: Path, root: Path) -> None:
    """Confirm the identity tree holds exactly what the pack promises."""
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    skill = (root / "pack" / "skill" / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")
    guidance = (root / "pack" / "guidance.md").read_text(encoding="utf-8")
    roles = json.loads((root / "pack" / "elections.json").read_text(encoding="utf-8"))["roles"]

    installed = identity / "skills" / SKILL_NAME / "SKILL.md"
    if not installed.is_file() or installed.read_text(encoding="utf-8") != skill:
        raise RuntimeCompatError("the pack skill is not in the organization identity")

    text = (identity / "guidance" / "default.md").read_text(encoding="utf-8")
    block = GUIDANCE_BEGIN.format(version=version) + "\n" + guidance.strip() + "\n" + GUIDANCE_END
    if text.count(block) != 1 or text.count(GUIDANCE_END) != 1:
        raise RuntimeCompatError("the pack guidance section is not in default guidance exactly once")

    present = {path.stem for path in (identity / "archetypes").glob("*.toml")}
    elected = sorted(present & set(roles))
    if "default" not in elected or len(elected) < 2:
        raise RuntimeCompatError(
            f"the scratch organization has too few pack roles to test elections: {elected}"
        )
    for role in elected:
        manifest = (identity / "archetypes" / f"{role}.toml").read_text(encoding="utf-8")
        skills = tomllib.loads(manifest).get("skills")
        if not isinstance(skills, list) or skills.count(SKILL_NAME) != 1:
            raise RuntimeCompatError(f"role {role} does not elect the pack skill once")
        if ELECTION_MARKER not in manifest:
            raise RuntimeCompatError(f"role {role} election is not marked as pack-owned")
    for role in sorted(present - set(roles)):
        manifest = (identity / "archetypes" / f"{role}.toml").read_text(encoding="utf-8")
        if SKILL_NAME in (tomllib.loads(manifest).get("skills") or []):
            raise RuntimeCompatError(f"role {role} elects the pack skill but is not a pack role")


def _check_release(release: Release, root: Path, work: Path) -> None:
    downloads = work / "download"
    downloads.mkdir()
    package = _download_package(release, downloads)
    package_root = _extract(package, work / "package")
    scratch = work / "org"
    scratch.mkdir()
    env = _scratch_environment(scratch, _free_port(), package_root)
    cli = env["TIGHTBEAM_CLI"]

    expected_version = release.tag.removeprefix("v").split("+", 1)[0]
    reported = _run([cli, "--version"], env, scratch, "CLI version").strip()
    if reported != expected_version:
        raise RuntimeCompatError(f"{release.tag} CLI reports version {reported!r}")

    log = work / "gateway.log"
    with log.open("wb") as log_file:
        gateway = subprocess.Popen(
            [str(package_root / "bin" / "tightbeam-gateway")],
            cwd=scratch,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_ready(gateway, env, scratch, log)
        _run([cli, "learn", BUNDLE], env, scratch, f"learning {BUNDLE}")
        identity = Path(env["TIGHTBEAM_BASE_DIR"]) / "identity"
        apply = [sys.executable, "-I", str(root / "bin" / "harklight_pack.py"), "apply", "--source-dir", str(root)]
        first = _run(apply, env, scratch, "pack apply")
        if "is applied" not in first:
            raise RuntimeCompatError("pack apply did not report an applied pack")
        check_applied(identity, root)
        before = _identity_digest(identity)
        second = _run(apply, env, scratch, "repeated pack apply")
        if "is already applied" not in second or _identity_digest(identity) != before:
            raise RuntimeCompatError("repeating pack apply changed the organization identity")
        _run([cli, "identity", "status"], env, scratch, "identity status after apply")
        if gateway.poll() is not None:
            raise RuntimeCompatError(f"gateway exited during the test: {_log_tail(log)}")
    finally:
        _stop(gateway, env, package_root, scratch)


def _require_isolated_host() -> None:
    if os.environ.get("HARKLIGHT_PACK_RUNTIME_ISOLATED") == "1" or os.environ.get("CI") == "true":
        if sys.platform == "linux" and platform.machine() in {"x86_64", "AMD64"}:
            return
        raise RuntimeCompatError("the runtime check needs a Linux x86_64 host")
    raise RuntimeCompatError(
        "the runtime check boots real gateways; run it in CI or set "
        "HARKLIGHT_PACK_RUNTIME_ISOLATED=1 on a host with no Tightbeam installation"
    )


def tested_versions(root: Path) -> tuple[str, ...]:
    """Return the Tightbeam release tags the pack at root passed against.

    Covers exactly the current and previous full releases. Raises
    RuntimeCompatError unless both pass.
    """
    root = Path(root).resolve()
    _require_isolated_host()
    window = discover()
    passed = []
    for release in window:
        with tempfile.TemporaryDirectory(prefix="harklight-pack-runtime-") as temp:
            try:
                _check_release(release, root, Path(temp))
            except RuntimeCompatError as error:
                raise RuntimeCompatError(f"{release.tag}: {error}") from error
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                raise RuntimeCompatError(f"{release.tag}: runtime check failed: {error}") from error
        passed.append(release.tag)
    if len(passed) != WINDOW:
        raise RuntimeCompatError("not every release in the support window passed")
    return tuple(sorted(passed))


def main() -> int:
    try:
        versions = tested_versions(Path(__file__).resolve().parents[1])
    except RuntimeCompatError as error:
        print(f"runtime compatibility check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"compatible_with_tightbeam": list(versions)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
