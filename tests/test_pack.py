from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "bin"))

import harklight_pack
import privacy_check
import sync_from_installation


class PrivacyCheckTests(unittest.TestCase):
    def test_private_terms_and_common_patterns_fail_without_echoing_values(self) -> None:
        findings = privacy_check.text_findings(
            "sample",
            "A note contains private-sentinel-term and alpha" + "@example.com",
            ["private-sentinel-term"],
            set(),
        )
        self.assertIn("sample: configured private term", findings)
        self.assertIn("sample: possible email address", findings)
        self.assertNotIn("private-sentinel-term", "\n".join(findings))

    def test_public_markdown_checks_unrecognized_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "notes.md").write_text(
                "A note about Unlistedplace.\n", encoding="utf-8"
            )
            findings = privacy_check.scan_repository(root)
        self.assertIn("notes.md: unrecognized proper noun", findings)

    def test_pull_request_memento_labels_are_not_private_names(self) -> None:
        findings = privacy_check.text_findings(
            "pull request body",
            "Tightbeam-Assignment: asg_123\nTightbeam-Work-Item: wi_456",
        )
        self.assertNotIn("pull request body: unrecognized proper noun", findings)

    def test_private_terms_match_whole_identifiers(self) -> None:
        whole = privacy_check.text_findings("sample", "the cat is here", ["cat"])
        embedded = privacy_check.text_findings("sample", "concatenate values", ["cat"])
        self.assertIn("sample: configured private term", whole)
        self.assertNotIn("sample: configured private term", embedded)


class SourceSyncTests(unittest.TestCase):
    def test_generates_only_allowlisted_pack_files(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "reference-identity"
        with tempfile.TemporaryDirectory() as temp:
            private_terms = Path(temp) / "terms.txt"
            private_terms.write_text("private-sentinel-term\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "HARKLIGHT_PACK_PRIVATE_TERMS_FILE": str(private_terms),
                },
            ):
                files, _ = sync_from_installation.generate(fixture)
        relative = {path.relative_to(ROOT).as_posix(): text for path, text in files.items()}
        self.assertEqual(
            set(relative),
            {
                "pack/skill/harklight-agent/SKILL.md",
                "pack/guidance.md",
                "pack/elections.json",
            },
        )
        self.assertEqual(
            json.loads(relative["pack/elections.json"])["roles"],
            ["coder", "default", "reviewer"],
        )
        self.assertIn(sync_from_installation.SKILL_MARKER, relative["pack/skill/harklight-agent/SKILL.md"])
        self.assertNotIn("fleet", relative["pack/skill/harklight-agent/SKILL.md"])
        self.assertIn("Reporting to the operator", relative["pack/guidance.md"])
        self.assertNotIn("local sender", relative["pack/skill/harklight-agent/SKILL.md"])

    def test_unknown_harklight_guidance_stops_sync(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "reference-identity"
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "identity"
            import shutil

            shutil.copytree(fixture, copied)
            extra = copied / "guidance" / "extra.md"
            extra.write_text("# Extra\n\nHarklight content is unknown here.\n", encoding="utf-8")
            private_terms = Path(temp) / "terms.txt"
            private_terms.write_text("private-sentinel-term\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "HARKLIGHT_PACK_PRIVATE_TERMS_FILE": str(private_terms),
                },
            ):
                with self.assertRaises(sync_from_installation.SyncError):
                    sync_from_installation.generate(copied)


class ApplyTests(unittest.TestCase):
    def _make_pack(self, root: Path) -> harklight_pack.Pack:
        skill = (
            "---\nname: harklight-agent\ndescription: Generic skill\n---\n\n"
            + harklight_pack.SKILL_MARKER
            + "\n\n# Harklight for Tightbeam agents\n"
        )
        guidance = "## Reporting to the operator on Harklight\n\nUse the skill."
        return harklight_pack.Pack("1.2.3", skill, guidance, ("coder", "default"))

    def test_apply_is_idempotent_and_removes_only_pack_owned_elections(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "base"
            identity = base / "identity"
            (identity / "guidance").mkdir(parents=True)
            (identity / "archetypes").mkdir(parents=True)
            (identity / "guidance" / "default.md").write_text(
                "# Local guidance\n\nKeep this paragraph.\n", encoding="utf-8"
            )
            (identity / "archetypes" / "default.toml").write_text(
                'name = "default"\nskills = ["base"]\n', encoding="utf-8"
            )
            (identity / "archetypes" / "coder.toml").write_text(
                'name = "coder"\nskills = ["base"]\n', encoding="utf-8"
            )
            (identity / "archetypes" / "reviewer.toml").write_text(
                'name = "reviewer"\n'
                + harklight_pack.ELECTION_MARKER
                + '\nskills = ["base", "harklight-agent"]\n',
                encoding="utf-8",
            )

            fakebin = Path(temp) / "fakebin"
            fakebin.mkdir()
            fake_cli = fakebin / "tightbeam"
            fake_cli.write_text(
                "#!/usr/bin/env python3\n"
                "import os, pathlib, sys\n"
                "args=sys.argv[1:]\n"
                "base=pathlib.Path(os.environ['TIGHTBEAM_BASE_DIR'])\n"
                "identity=base/'identity'\n"
                "role=args[2]\n"
                "source=pathlib.Path(args[args.index('--file')+1])\n"
                "if '--skill' in args: target=identity/'skills'/'harklight-agent'/'SKILL.md'\n"
                "elif '--manifest' in args: target=identity/'archetypes'/f'{role}.toml'\n"
                "else: target=identity/'guidance'/f'{role}.md'\n"
                "target.parent.mkdir(parents=True,exist_ok=True)\n"
                "target.write_bytes(source.read_bytes())\n"
                "with open(os.environ['FAKE_CLI_LOG'],'a',encoding='utf-8') as f: f.write(target.name+'\\n')\n",
                encoding="utf-8",
            )
            fake_cli.chmod(0o755)
            log = Path(temp) / "calls.log"
            pack = self._make_pack(Path(temp))
            with patch.dict(
                os.environ,
                {
                    "PATH": str(fakebin) + os.pathsep + os.environ.get("PATH", ""),
                    "TIGHTBEAM_BASE_DIR": str(base),
                    "TIGHTBEAM_CLI": "tightbeam",
                    "FAKE_CLI_LOG": str(log),
                },
            ):
                harklight_pack._apply(identity, base, pack)
                first_count = len(log.read_text(encoding="utf-8").splitlines())
                harklight_pack._apply(identity, base, pack)
                second_count = len(log.read_text(encoding="utf-8").splitlines())

            self.assertGreater(first_count, 0)
            self.assertEqual(first_count, second_count)
            guidance = (identity / "guidance" / "default.md").read_text(encoding="utf-8")
            self.assertIn("Keep this paragraph.", guidance)
            self.assertIn("BEGIN HARKLIGHT FOR TIGHTBEAM v1.2.3", guidance)
            self.assertNotIn("HARKLIGHT_PACK_ELECTED", (identity / "archetypes" / "reviewer.toml").read_text(encoding="utf-8"))
            self.assertIn("harklight-agent", (identity / "archetypes" / "coder.toml").read_text(encoding="utf-8"))


class ReleaseFetchTests(unittest.TestCase):
    def test_update_download_checks_archive_checksum(self) -> None:
        archive_buffer = io.BytesIO()
        version = "1.2.3"
        root = f"harklight-pack-v{version}"
        files = {
            f"{root}/VERSION": version.encode(),
            f"{root}/pack/skill/harklight-agent/SKILL.md": (
                "---\nname: harklight-agent\n---\n"
                + harklight_pack.SKILL_MARKER
                + "\n"
            ).encode(),
            f"{root}/pack/guidance.md": b"## Harklight\n",
            f"{root}/pack/elections.json": b'{"roles":["default"]}\n',
        }
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        archive_bytes = archive_buffer.getvalue()
        archive_name = f"harklight-pack-v{version}.tar.gz"
        checksum = hashlib.sha256(archive_bytes).hexdigest()
        release = {
            "tag_name": f"v{version}",
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": archive_name, "browser_download_url": "asset://archive"},
                {"name": "SHA256SUMS", "browser_download_url": "asset://sums"},
            ],
        }

        def fake_request(url: str, accept: str = "") -> bytes:
            if url.endswith("/releases/latest"):
                return json.dumps(release).encode()
            if url == "asset://archive":
                return archive_bytes
            if url == "asset://sums":
                return f"{checksum}  {archive_name}\n".encode()
            raise AssertionError("unexpected release URL")

        with patch.object(harklight_pack, "_request", side_effect=fake_request):
            pack = harklight_pack._download_latest_pack()
        self.assertEqual(pack.version, version)
        self.assertEqual(pack.roles, ("default",))


if __name__ == "__main__":
    unittest.main()
