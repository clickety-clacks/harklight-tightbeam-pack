#!/usr/bin/env python3
"""Read allowlisted identity sources and open a privacy-checked sync PR."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from privacy_check import read_private_terms, scan_repository


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "pack"
SKILL_RELATIVE = Path("skills/harklight-agent/SKILL.md")
DEFAULT_GUIDANCE_RELATIVE = Path("guidance/default.md")
PACK_SKILL = Path("skill/harklight-agent/SKILL.md")
PACK_GUIDANCE = Path("guidance.md")
PACK_ELECTIONS = Path("elections.json")
GUIDANCE_BEGIN = "<!-- BEGIN HARKLIGHT FOR TIGHTBEAM -->"
GUIDANCE_END = "<!-- END HARKLIGHT FOR TIGHTBEAM -->"
SKILL_MARKER = "<!-- HARKLIGHT_PACK_MANAGED -->"
ELECTION_MARKER = "# HARKLIGHT_PACK_ELECTED"
SYNC_BRANCH = "sync/from-installation"
PR_TITLE = "Sync Harklight for Tightbeam content"
PR_BODY = """Refresh the generated Harklight for Tightbeam pack from its
allowlisted identity sources.

The source read was read-only. The local privacy and source-shape checks passed;
CI repeats public-content checks on this pull request.

Tightbeam-Assignment: asg_cf1d254f-808d-4680-9257-b73a0c004407
Tightbeam-Work-Item: wi_e5035dbd-6176-4e7a-92d9-61b9eb1d6e12
"""
COMMIT_MESSAGE = "Sync Harklight pack from reference identity"
GUIDANCE_RE = re.compile(r"(?m)^##\s+Reporting to (?P<operator>.+?) on Harklight\s*$")
DEFAULT_RE = re.compile(r"(?m)^##\s+Decisions only (?P<operator>.+?) can act on in person\s*$")
PRIVATE_SECTION_RE = re.compile(
    r"(?m)^##\s+Existing .+ sender and compatibility route\s*$"
)
HOME_LINK_RE = re.compile(r"\]\(\s*~" + re.escape(os.sep))
HOME_ABSOLUTE_RE = re.compile(r"/(?:" + "ho" + "me" + r"|Users)/[A-Za-z0-9._-]+")
EXPECTED_SKILL_HEADINGS = [
    "# Harklight for Tightbeam agents",
    "## Automatic lifecycle for your own messages",
    "## Configuration and sending",
    "## Revise, retract or supersede",
    "## Read results and settle an uncertain send",
    "## Read one of your own sent messages",
    "## Handle a delivered entry",
    "## Raw command recovery and references",
]


@dataclass(frozen=True)
class Section:
    start: int
    end: int
    heading: str
    body: str
    operator: str


class SyncError(RuntimeError):
    pass


def identity_root_from_environment() -> Path:
    configured = os.environ.get("TIGHTBEAM_IDENTITY_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    base = (
        os.environ.get("TIGHTBEAM_BASE_DIR")
        or os.environ.get("TIGHTBEAM_HOME")
        or str(Path.home() / ".tightbeam")
    )
    return (Path(base).expanduser() / "identity").resolve()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise SyncError("an allowlisted identity source is unavailable") from error


def _markdown_sections(text: str) -> list[tuple[int, int, str]]:
    headings = list(re.finditer(r"(?m)^#{1,6}\s+.+$", text))
    result: list[tuple[int, int, str]] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        result.append((heading.start(), end, heading.group(0).strip()))
    return result


def _extract_heading_section(
    path: Path, text: str, pattern: re.Pattern[str], stop_include: bool = False
) -> list[Section]:
    matches: list[Section] = []
    for heading_match in re.finditer(r"(?m)^#{1,6}\s+.+$", text):
        start = heading_match.start()
        body_start = heading_match.end()
        heading = heading_match.group(0).strip()
        match = pattern.match(heading)
        if not match:
            continue
        end = _next_heading_start(text, body_start)
        include = re.search(r"(?m)^#include\b", text[body_start:end]) if stop_include else None
        if include:
            end = body_start + include.start()
        matches.append(
            Section(
                start=start,
                end=end,
                heading=heading,
                body=text[body_start:end].strip(),
                operator=match.group("operator").strip(),
            )
        )
    return matches


def _next_heading_start(text: str, offset: int) -> int:
    match = re.search(r"(?m)^#{1,6}\s+", text[offset:])
    return offset + match.start() if match else len(text)


def _line_starts(text: str, start: int, end: int) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    offset = start
    for line in text[start:end].splitlines(keepends=True):
        result.append((offset, line.rstrip("\r\n")))
        offset += len(line)
    return result


def _normalize_operator(text: str, operator: str) -> str:
    if operator.casefold() != "the operator":
        text = re.sub(
            r"(?<!\w)" + re.escape(operator) + r"(?!\w)",
            "the operator",
            text,
            flags=re.I,
        )

    replacements = {"he": "they", "him": "them", "his": "their"}

    def replace_pronoun(match: re.Match[str]) -> str:
        replacement = replacements[match.group(0).casefold()]
        return replacement.capitalize() if match.group(0)[0].isupper() else replacement

    text = re.sub(r"\b(?:he|him|his)\b", replace_pronoun, text, flags=re.I)
    for singular, plural in (
        ("they answers", "they answer"),
        ("they needs", "they need"),
        ("they has", "they have"),
        ("they does", "they do"),
        ("they is", "they are"),
    ):
        text = re.sub(r"\b" + singular + r"\b", plural, text, flags=re.I)
    return text


def _clean_skill(skill: str) -> str:
    frontmatter_match = re.match(r"\A---\n(.*?)\n---\n", skill, flags=re.S)
    if not frontmatter_match:
        raise SyncError("the allowlisted skill has unfamiliar front matter")
    description_match = re.search(
        r"(?m)^description:\s*(.+)$", frontmatter_match.group(1)
    )
    if not description_match:
        raise SyncError("the allowlisted skill description is missing")
    frontmatter = frontmatter_match.group(1)
    description = description_match.group(1).replace(
        "other fleet hosts", "remote hosts"
    )
    frontmatter = re.sub(
        r"(?m)^description:\s*.+$",
        "description: " + description,
        frontmatter,
    )
    body = skill[frontmatter_match.end() :]

    quote_start = re.search(r"(?m)^> ", body)
    first_section = re.search(r"(?m)^## Automatic lifecycle for your own messages\s*$", body)
    if not first_section:
        raise SyncError("the allowlisted skill lifecycle section is missing")
    if quote_start and quote_start.start() < first_section.start():
        body = (
            body[: quote_start.start()]
            + "> Follow the installed Tightbeam and Harklight help for exact options.\n\n"
            + body[first_section.start() :]
        )

    private_sections = list(PRIVATE_SECTION_RE.finditer(body))
    if len(private_sections) != 1:
        raise SyncError("the allowlisted skill's compatibility section changed")
    private_section = private_sections[0]
    if re.search(r"(?m)^#{1,6}\s+.+$", body[private_section.end() :]):
        raise SyncError("the allowlisted skill has an unrecognized trailing section")
    body = body[: private_section.start()].rstrip() + "\n"

    normalized_blocks: list[str] = []
    for block in re.split(r"\n\s*\n", body):
        if HOME_LINK_RE.search(block) or HOME_ABSOLUTE_RE.search(block):
            normalized_blocks.append(
                "For raw commands outside Tightbeam, consult the installed "
                "Harklight Agent skill and its help. This skill covers "
                "Tightbeam-managed subscriptions and wakes."
            )
        else:
            normalized_blocks.append(block)
    body = "\n\n".join(normalized_blocks).rstrip() + "\n"
    headings = [
        match.group(0).strip()
        for match in re.finditer(r"(?m)^#{1,6}\s+.+$", body)
    ]
    if headings != EXPECTED_SKILL_HEADINGS:
        raise SyncError("the allowlisted skill has a new or changed section")
    body = body.replace("including from other fleet hosts", "including from remote hosts")
    return (
        "---\n"
        + frontmatter
        + "\n---\n\n"
        + SKILL_MARKER
        + "\n\n"
        + body.lstrip()
    )


def _read_guidance_sources(identity_root: Path) -> tuple[str, list[Section], list[str]]:
    default_path = identity_root / DEFAULT_GUIDANCE_RELATIVE
    default_text = _read(default_path)
    default_sections = _extract_heading_section(
        default_path, default_text, DEFAULT_RE, stop_include=True
    )
    if len(default_sections) != 1:
        raise SyncError("the default Harklight guidance section is missing or ambiguous")
    default_section = default_sections[0]
    if not all(
        token in default_section.body.casefold()
        for token in ("harklight", "harklight-agent", "tightbeam harklight-send")
    ):
        raise SyncError("the default Harklight guidance section changed shape")

    guidance_sources = sorted((identity_root / "guidance").rglob("*.md"))
    reporting_sections: list[Section] = []
    indexed: dict[Path, tuple[str, list[Section]]] = {}
    for path in guidance_sources:
        text = _read(path)
        sections = _extract_heading_section(path, text, GUIDANCE_RE)
        indexed[path] = (text, sections)
        reporting_sections.extend(sections)
    if len(reporting_sections) != 1:
        raise SyncError("the operator Harklight guidance section is missing or ambiguous")
    reporting = reporting_sections[0]
    if not all(
        token in reporting.body.casefold()
        for token in ("tightbeam harklight-send", "harklight-agent", "answer")
    ):
        raise SyncError("the operator Harklight guidance section changed shape")

    allowed: dict[Path, list[tuple[int, int]]] = {
        default_path: [(default_section.start, default_section.end)]
    }
    for path, (_, sections) in indexed.items():
        if sections:
            allowed.setdefault(path, []).extend((section.start, section.end) for section in sections)
    for path, (text, _) in indexed.items():
        occurrences = list(re.finditer(r"harklight", text, flags=re.I))
        ranges = allowed.get(path, [])
        if any(
            not any(start <= occurrence.start() < end for start, end in ranges)
            for occurrence in occurrences
        ):
            raise SyncError("an unrecognized Harklight guidance section was found")
    for path in guidance_sources:
        if path == default_path:
            continue
        text = _read(path)
        occurrences = list(re.finditer(r"harklight", text, flags=re.I))
        ranges = allowed.get(path, [])
        if occurrences and not ranges:
            raise SyncError("an unrecognized Harklight guidance section was found")

    default_body = _normalize_operator(
        "## Decisions only the operator can act on in person\n\n" + default_section.body,
        default_section.operator,
    )
    default_body = re.sub(
        r"(?m)^## Decisions only .+ can act on in person$",
        "## Decisions the operator must handle in person",
        default_body,
    )
    reporting_body = _normalize_operator(
        "## Reporting to the operator on Harklight\n\n" + reporting.body,
        reporting.operator,
    )
    reporting_body = re.sub(
        r"(?m)^## Reporting to .+ on Harklight$",
        "## Reporting to the operator on Harklight",
        reporting_body,
    )
    reporting_body = re.sub(
        r"(?m)^- \*\*Don't\*\* use the .+ script\. Don't use .+ to\n"
        r"  start new messages or to listen for replies\.\n?",
        "",
        reporting_body,
    )
    if re.search(
        r"harklight-[a-z0-9_-]+\s+script|~" + re.escape(os.sep),
        reporting_body,
        re.I,
    ):
        raise SyncError("an organization-specific helper remains in Harklight guidance")
    combined = default_body.rstrip() + "\n\n" + reporting_body.strip() + "\n"
    return combined, [default_section, reporting], [
        default_section.operator,
        reporting.operator,
    ]


def _extract_elections(identity_root: Path) -> tuple[list[str], list[str]]:
    archetypes = identity_root / "archetypes"
    if not archetypes.is_dir():
        raise SyncError("the archetype directory is unavailable")
    roles: list[str] = []
    host_terms: list[str] = []
    for path in sorted(archetypes.glob("*.toml")):
        try:
            data = tomllib.loads(_read(path))
        except tomllib.TOMLDecodeError as error:
            raise SyncError("an archetype manifest is malformed") from error
        name = data.get("name")
        skills = data.get("skills")
        if not isinstance(name, str) or not isinstance(skills, list):
            raise SyncError("an archetype manifest has an unfamiliar shape")
        if name != path.stem:
            raise SyncError("an archetype name does not match its manifest")
        if "harklight-agent" in skills:
            roles.append(name)
        where = data.get("where", [])
        if where is not None:
            if not isinstance(where, list) or any(not isinstance(item, str) for item in where):
                raise SyncError("an archetype placement list has an unfamiliar shape")
            host_terms.extend(where)
    return sorted(set(roles)), sorted(set(host_terms))


def source_private_terms(identity_root: Path, operators: list[str], host_terms: list[str]) -> list[str]:
    terms = [*operators, *host_terms]
    configured = os.environ.get("HARKLIGHT_PACK_PRIVATE_TERMS_FILE")
    if configured:
        try:
            terms.extend(read_private_terms(Path(configured).expanduser()))
        except (OSError, ValueError) as error:
            raise SyncError("the configured private-terms file is unavailable") from error
    else:
        raise SyncError("configure HARKLIGHT_PACK_PRIVATE_TERMS_FILE before opening a sync PR")
    return sorted({term.strip() for term in terms if len(term.strip()) >= 3})


def generate(identity_root: Path) -> tuple[dict[Path, str], list[str]]:
    if not identity_root.is_dir():
        raise SyncError("the configured identity directory is unavailable")
    expected_skill = identity_root / SKILL_RELATIVE
    skill = _clean_skill(_read(expected_skill))
    guidance, _, operators = _read_guidance_sources(identity_root)
    roles, hosts = _extract_elections(identity_root)
    if not roles:
        raise SyncError("the reference identity has no Harklight skill elections")

    skill_root = identity_root / "skills"
    for path in skill_root.rglob("*"):
        if not path.is_file() or path == expected_skill:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "harklight" in path.as_posix().casefold() or re.search(
            r"harklight", content, flags=re.I
        ):
            raise SyncError("an unrecognized Harklight skill source was found")

    files = {
        PACK / PACK_SKILL: skill,
        PACK / PACK_GUIDANCE: guidance,
        PACK / PACK_ELECTIONS: json.dumps({"roles": roles}, indent=2) + "\n",
    }
    return files, source_private_terms(identity_root, operators, hosts)


def _run(
    args: list[str], cwd: Path | None = None, capture: bool = True
) -> str:
    if cwd is None:
        cwd = ROOT
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=capture,
        text=True,
    )
    if result.returncode != 0:
        raise SyncError("a required repository operation failed")
    return result.stdout.strip() if capture else ""


def _version_tuple(raw: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", raw.strip())
    return tuple(map(int, match.groups())) if match else None


def _next_version(base: str) -> str:
    parsed = _version_tuple(base)
    if parsed is None:
        return "0.1.0"
    major, minor, patch = parsed
    return f"{major}.{minor}.{patch + 1}"


def _update_changelog(version: str) -> None:
    path = ROOT / "CHANGELOG.md"
    current = path.read_text(encoding="utf-8")
    heading = f"## v{version}"
    if heading in current:
        return
    entry = (
        f"{heading}\n\n"
        "Refreshed the Harklight skill and operator guidance from the "
        "allowlisted reference identity.\n\n"
    )
    lines = current.splitlines(keepends=True)
    insertion = next(
        (index + 1 for index, line in enumerate(lines) if line.startswith("# Changelog")),
        1,
    )
    lines.insert(insertion, "\n" + entry)
    path.write_text("".join(lines), encoding="utf-8")


def _read_remote_text(path: str, fallback: str = "") -> str:
    result = subprocess.run(
        ["git", "show", f"origin/main:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else fallback


def _list_sync_prs() -> list[dict[str, object]]:
    return json.loads(
        _run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--head",
                SYNC_BRANCH,
                "--json",
                "number,url,title",
            ]
        )
    )


def _remote_sync_branch_oid() -> str | None:
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", f"refs/heads/{SYNC_BRANCH}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SyncError("the remote sync branch could not be inspected")
    lines = [line.split()[0] for line in result.stdout.splitlines() if line.split()]
    if len(lines) > 1:
        raise SyncError("the remote sync branch reference is ambiguous")
    return lines[0] if lines else None


def _open_sync_pr() -> tuple[bool, str | None]:
    start_status = _run(["git", "status", "--porcelain"])
    if start_status:
        raise SyncError("the repository working tree must be clean before sync")
    branch = _run(["git", "branch", "--show-current"])
    if branch not in {"main", SYNC_BRANCH}:
        raise SyncError("the sync job is running from an unexpected branch")
    _run(["git", "fetch", "origin", "main"])
    open_prs = _list_sync_prs()
    if open_prs:
        _run(["git", "fetch", "origin", SYNC_BRANCH])
        _run(["git", "checkout", "-B", SYNC_BRANCH, f"origin/{SYNC_BRANCH}"])
        return True, None

    # A merged or closed PR leaves the reserved remote branch behind. Start the
    # next sync at the current main tip and replace that stale branch only if
    # it still has the exact object observed here.
    if branch == SYNC_BRANCH:
        _run(["git", "checkout", "main"])
    _run(["git", "merge", "--ff-only", "origin/main"])
    expected_remote = _remote_sync_branch_oid()
    _run(["git", "checkout", "-B", SYNC_BRANCH, "origin/main"])
    return False, expected_remote


def _push_sync_branch(open_pr_exists: bool, expected_remote: str | None) -> None:
    command = ["git", "push"]
    if open_pr_exists:
        command.append("--set-upstream")
        command.extend(["origin", SYNC_BRANCH])
    else:
        if expected_remote:
            command.append(
                f"--force-with-lease=refs/heads/{SYNC_BRANCH}:{expected_remote}"
            )
        command.append("--set-upstream")
        command.extend(["origin", SYNC_BRANCH])
    _run(command)


def _publication_text() -> dict[str, str]:
    return {
        "commit message": COMMIT_MESSAGE,
        "pull request title": PR_TITLE,
        "pull request body": PR_BODY,
    }


def _publish(files: dict[Path, str], private_terms: list[str], auto_merge: bool) -> None:
    open_pr_exists, expected_remote = _open_sync_pr()
    before = {path: path.read_bytes() if path.exists() else None for path in files}
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    changed = any(
        before[path] != path.read_bytes()
        for path in files
    )
    if not changed:
        print("reference sources match the open pack; no pull request update")
        return

    base_version = _read_remote_text("VERSION", "0.0.0-dev").strip()
    current_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if _version_tuple(current_version) is None or current_version == base_version:
        version = _next_version(base_version)
    else:
        version = current_version
    (ROOT / "VERSION").write_text(version + "\n", encoding="utf-8")
    _update_changelog(version)

    findings = scan_repository(ROOT, private_terms, _publication_text())
    if findings:
        raise SyncError("privacy check failed before repository publication")
    _run(["git", "add", "--", "pack", "VERSION", "CHANGELOG.md"])
    staged = _run(["git", "diff", "--cached", "--name-only"])
    if not staged:
        print("reference sources match the open pack; no pull request update")
        return
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Harklight Pack Sync"
    env["GIT_AUTHOR_EMAIL"] = "harklight-pack-sync"
    env["GIT_COMMITTER_NAME"] = "Harklight Pack Sync"
    env["GIT_COMMITTER_EMAIL"] = "harklight-pack-sync"
    commit = subprocess.run(
        ["git", "commit", "-m", COMMIT_MESSAGE],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode != 0:
        raise SyncError("the sync commit could not be created")
    try:
        _push_sync_branch(open_pr_exists, expected_remote)
    except SyncError:
        raise SyncError("the sync branch could not be pushed")

    open_prs = json.loads(
        _run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--head",
                SYNC_BRANCH,
                "--json",
                "number,url,title",
            ]
        )
    )
    if not open_prs:
        body_file = ROOT / ".sync-pr-body"
        body_file.write_text(PR_BODY, encoding="utf-8")
        try:
            _run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--base",
                    "main",
                    "--head",
                    SYNC_BRANCH,
                    "--title",
                    PR_TITLE,
                    "--body-file",
                    str(body_file),
                ]
            )
        finally:
            body_file.unlink(missing_ok=True)
    if auto_merge:
        _run(["gh", "pr", "merge", "--auto", "--squash", SYNC_BRANCH])
    print("privacy-checked sync pull request is ready")


def run(open_pr: bool, preview: bool) -> int:
    identity_root = identity_root_from_environment()
    files, private_terms = generate(identity_root)
    generated_texts = {
        path.relative_to(ROOT).as_posix(): content for path, content in files.items()
    }
    findings = scan_repository(ROOT, private_terms, generated_texts)
    if findings:
        raise SyncError("privacy check failed before pack generation")
    if open_pr:
        policy = json.loads((ROOT / "sync-policy.json").read_text(encoding="utf-8"))
        policy_name = policy.get("publish_policy")
        if policy_name not in {"review", "auto_merge_clean"}:
            raise SyncError("the configured publish policy is not recognized")
        _publish(files, private_terms, policy_name == "auto_merge_clean")
    elif preview:
        for path in files:
            print(f"would update {path.relative_to(ROOT)}")
    else:
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        print("allowlisted pack files refreshed; no repository publication requested")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity-dir", type=Path)
    parser.add_argument("--open-pr", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    if args.identity_dir:
        os.environ["TIGHTBEAM_IDENTITY_DIR"] = str(args.identity_dir)
    try:
        return run(args.open_pr, args.preview)
    except (OSError, ValueError, SyncError) as error:
        print(f"sync refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
