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
    "Some",
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


def _proper_noun_findings(text: str, known_lower_words: set[str]) -> list[str]:
    findings: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for match in re.finditer(r"\b[A-Z][a-z]{2,}\b", line):
            word = match.group(0)
            prefix = line[: match.start()]
            if not prefix.strip() or not prefix.strip(" -*•>0123456789.)"):
                continue
            if prefix.rstrip().endswith((".", "!", "?")):
                continue
            if word in PUBLIC_NAMES or word in COMMON_CAPS or word.casefold() in known_lower_words:
                continue
            findings.append(word)
    return findings


def text_findings(
    label: str,
    text: str,
    private_terms: Iterable[str] = (),
    known_lower_words: set[str] | None = None,
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
        lower_words = known_lower_words if known_lower_words is not None else set(
            re.findall(r"\b[a-z][a-z'-]{2,}\b", text)
        )
        if _proper_noun_findings(text, lower_words):
            findings.append(f"{label}: unrecognized proper noun")
    return findings


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _repo_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _known_lower_words(texts: Iterable[str]) -> set[str]:
    words: set[str] = set()
    for text in texts:
        words.update(re.findall(r"\b[a-z][a-z'-]{2,}\b", text))
    return words


def _event_texts() -> dict[str, str]:
    result: dict[str, str] = {}
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path:
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"GitHub event": ""}
        pull = event.get("pull_request") or {}
        if pull:
            result["pull request title"] = str(pull.get("title") or "")
            result["pull request body"] = str(pull.get("body") or "")
    try:
        commit_text = subprocess.run(
            ["git", "log", "-n", "10", "--format=%B"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        commit_text = ""
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
    lower_words = _known_lower_words(
        [text for _, text in texts] + [text for _, text in additional]
    )
    findings: list[str] = []
    terms = tuple(private_terms)
    for label, text in texts:
        suffix = Path(label).suffix.lower()
        findings.extend(
            text_findings(
                label,
                text,
                terms,
                lower_words,
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
        findings.extend(text_findings(label, text, terms, lower_words))
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ci", action="store_true")
    parser.add_argument("--private-terms", type=Path)
    args = parser.parse_args()
    terms_path = args.private_terms
    if terms_path is None and not args.ci:
        configured = os.environ.get("HARKLIGHT_PACK_PRIVATE_TERMS_FILE")
        if configured:
            terms_path = Path(configured)
    try:
        terms = read_private_terms(terms_path)
    except (OSError, ValueError) as error:
        print(f"privacy check refused: {error}", file=sys.stderr)
        return 2
    extra = _event_texts() if args.ci else {}
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
