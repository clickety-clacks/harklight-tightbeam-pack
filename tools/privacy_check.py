#!/usr/bin/env python3
"""Fail-closed checks for public pack files and publication text."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", "__pycache__", "dist"}
PUBLIC_NAMES = {
    "Harklight",
    "Tightbeam",
    "GitHub",
    "Agent",
    "Codex",
    "Claude",
    "Python",
    "Markdown",
    "JSON",
    "TOML",
    "MIT",
    "UTC",
    "README",
    "VERSION",
    "SHA256",
    "HTTP",
    "HTTPS",
    "API",
    "CLI",
    "URL",
    "ACK",
    "Seen",
    "Linux",
    "macOS",
    "Unix",
    "Git",
    "Bash",
    "Actions",
    "Server",
    "Python",
    "Proceed",
    "Defer",
    "Unit",
    "Description",
    "Service",
    "Type",
    "Environment",
    "Timer",
    "Persistent",
    "Install",
    "WantedBy",
    "Assignment",
    "Work",
    "Item",
}
COMMON_CAPS = {
    "A",
    "About",
    "After",
    "All",
    "An",
    "And",
    "Apply",
    "Add",
    "Automatic",
    "Both",
    "Changes",
    "Configure",
    "Do",
    "Each",
    "Existing",
    "For",
    "If",
    "In",
    "It",
    "Keep",
    "MIT",
    "New",
    "No",
    "Only",
    "Or",
    "Our",
    "Python",
    "Run",
    "Set",
    "Start",
    "Standalone",
    "Some",
    "Sync",
    "The",
    "This",
    "To",
    "Use",
    "When",
    "With",
}


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    home_word = "ho" + "me"
    internal_suffix = ".ts" + ".net"
    private_key_header = "-" * 5 + "BEGIN"
    return [
        ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
        (
            "absolute home path",
            re.compile(r"/(?:" + home_word + r"|Users)/[A-Za-z0-9._-]+"),
        ),
        ("home-relative path", re.compile("~" + re.escape(os.sep))),
        (
            "internal hostname",
            re.compile(
                r"\b(?:[A-Z0-9-]+\.)+(?:local|internal|lan|corp|"
                + re.escape(internal_suffix.lstrip("."))
                + r")\b",
                re.I,
            ),
        ),
        (
            "private key material",
            re.compile(re.escape(private_key_header) + r"[^\n]*PRIVATE KEY", re.I),
        ),
        (
            "credential-shaped token",
            re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|(?:sk|rk)-[A-Za-z0-9]{24,})\b"),
        ),
    ]


def _extract_ips(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])", text):
        raw = match.group(0)
        try:
            ipaddress.ip_address(raw)
        except ValueError:
            continue
        found.append(raw)
    return found


def _proper_noun_findings(text: str) -> list[str]:
    findings: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        words = list(re.finditer(r"\b[A-Z][a-z]{2,}\b", line))
        for first, second in zip(words, words[1:]):
            gap = line[first.end() : second.start()]
            if not gap.isspace():
                continue
            pair = (first.group(0), second.group(0))
            if all(word in PUBLIC_NAMES or word in COMMON_CAPS for word in pair):
                continue
            findings.append("unrecognized name")
            break
    return findings


def text_findings(
    label: str,
    text: str,
    private_terms: Iterable[str] = (),
    check_names: bool = True,
) -> list[str]:
    findings: list[str] = []
    for description, pattern in _patterns():
        if pattern.search(text):
            findings.append(f"{label}: possible {description}")
    if _extract_ips(text):
        findings.append(f"{label}: possible internal IP address")

    lowered = text.casefold()
    for term in private_terms:
        candidate = term.strip().casefold()
        if len(candidate) >= 3 and re.search(
            r"(?<![A-Za-z0-9])" + re.escape(candidate) + r"(?![A-Za-z0-9])",
            lowered,
        ):
            findings.append(f"{label}: configured private term")
            break

    if check_names:
        if _proper_noun_findings(text):
            findings.append(f"{label}: unrecognized proper noun")
    return findings


def _read_text(path: Path) -> str | None:
    if path.is_symlink():
        try:
            return os.readlink(path)
        except OSError:
            return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _repo_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if (not path.is_file() and not path.is_symlink()) or any(
            part in SKIP_PARTS for part in path.parts
        ):
            continue
        files.append(path)
    return sorted(files)


def _event_texts() -> dict[str, str]:
    result: dict[str, str] = {}
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path:
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("GitHub event metadata is unavailable") from error
        pull = event.get("pull_request") or {}
        if pull:
            result["pull request title"] = str(pull.get("title") or "")
            result["pull request body"] = str(pull.get("body") or "")
    revision = os.environ.get("HARKLIGHT_PACK_CI_GIT_REF", "HEAD")
    if not re.fullmatch(r"(?:HEAD|refs/remotes/scan/[0-9]+)", revision):
        raise ValueError("CI source revision is invalid")
    try:
        commit_text = subprocess.run(
            [
                "git",
                "log",
                "-n",
                "10",
                "--format=%B",
                "--end-of-options",
                revision,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("CI commit messages are unavailable") from error
    if commit_text:
        result["recent commit messages"] = commit_text
    return result


def scan_repository(
    root: Path,
    private_terms: Iterable[str] = (),
    extra_texts: dict[str, str] | None = None,
) -> list[str]:
    paths = _repo_files(root)
    texts: list[tuple[str, str]] = []
    for path in paths:
        text = _read_text(path)
        if text is not None:
            texts.append((path.relative_to(root).as_posix(), text))
    additional = list((extra_texts or {}).items())
    findings: list[str] = []
    terms = tuple(private_terms)
    for label, text in texts:
        suffix = Path(label).suffix.lower()
        findings.extend(
            text_findings(
                label,
                text,
                terms,
                check_names=(
                    label.startswith("pack/")
                    or suffix in {
                        ".md",
                        ".txt",
                        ".yml",
                        ".yaml",
                        ".toml",
                        ".json",
                        ".service",
                        ".timer",
                        ".ini",
                    }
                ),
            )
        )
    for label, text in additional:
        findings.extend(text_findings(label, text, terms))
    return sorted(set(findings))


def read_private_terms(path: Path | None) -> list[str]:
    if path is None:
        return []
    if not path.is_file():
        raise ValueError("configured private-terms file is unavailable")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


CI_PRIVATE_CATEGORIES = {"machine", "person", "user"}
CI_ALLOWED_CATEGORIES = CI_PRIVATE_CATEGORIES | {
    "email",
    "hostname",
    "path",
    "other",
}


def private_terms_from_environment() -> list[str]:
    """Read categorized private terms without exposing their values in diagnostics."""
    raw = os.environ.get("HARKLIGHT_PACK_PRIVATE_TERMS", "")
    if not raw.strip():
        raise ValueError("CI private-term configuration is unavailable")
    values: list[str] = []
    categories: set[str] = set()
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        category, separator, value = line.partition("|")
        category = category.strip().casefold()
        value = value.strip()
        if (
            not separator
            or category not in CI_ALLOWED_CATEGORIES
            or len(value) < 3
            or "\n" in value
        ):
            raise ValueError("CI private-term configuration is malformed")
        categories.add(category)
        values.append(value)
    missing = CI_PRIVATE_CATEGORIES - categories
    if missing:
        raise ValueError("CI private-term categories are incomplete")
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ci", action="store_true")
    parser.add_argument("--private-terms", type=Path)
    args = parser.parse_args()
    terms_path = args.private_terms
    if args.ci:
        try:
            terms = private_terms_from_environment()
        except ValueError as error:
            print(f"privacy check refused: {error}", file=sys.stderr)
            return 2
    else:
        if terms_path is None:
            configured = os.environ.get("HARKLIGHT_PACK_PRIVATE_TERMS_FILE")
            if configured:
                terms_path = Path(configured)
        try:
            terms = read_private_terms(terms_path)
        except (OSError, ValueError) as error:
            print(f"privacy check refused: {error}", file=sys.stderr)
            return 2
    try:
        extra = _event_texts() if args.ci else {}
    except ValueError as error:
        print(f"privacy check refused: {error}", file=sys.stderr)
        return 2
    findings = scan_repository(args.root.resolve(), terms, extra)
    if findings:
        print("privacy check failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("privacy check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
