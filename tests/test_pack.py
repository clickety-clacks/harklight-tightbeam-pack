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
import release as release_tool
import sync_from_installation


class PrivacyCheckTests(unittest.TestCase):
    def test_private_terms_and_common_patterns_fail_without_echoing_values(self) -> None:
        findings = privacy_check.text_findings(
            "sample",
            "A note contains private-sentinel-term and alpha" + "@example.com",
            ["private-sentinel-term"],
        )
        self.assertIn("sample: configured private term", findings)
        self.assertIn("sample: possible email address", findings)
        self.assertNotIn("private-sentinel-term", "\n".join(findings))

    def test_only_internal_addresses_and_real_emails_are_flagged(self) -> None:
        def findings(text: str) -> list[str]:
            return privacy_check.text_findings("sample", text)

        self.assertEqual(findings("send from noreply" + "@example.com"), [])
        self.assertEqual(findings("see 8." + "8.8.8"), [])
        self.assertIn("sample: possible internal IP address", findings("host 10." + "1.2.3"))
        self.assertIn("sample: possible internal IP address", findings("host 192." + "168.0.9"))
        self.assertIn("sample: possible internal IP address", findings("at 127." + "0.0.1"))
        self.assertIn("sample: possible email address", findings("mail alice" + "@example.com"))

    def test_private_terms_match_whole_identifiers(self) -> None:
        whole = privacy_check.text_findings("sample", "the cat is here", ["cat"])
        embedded = privacy_check.text_findings("sample", "concatenate values", ["cat"])
        self.assertIn("sample: configured private term", whole)
        self.assertNotIn("sample: configured private term", embedded)

    def test_private_names_match_at_line_start_bullet_and_after_period(self) -> None:
        findings = privacy_check.text_findings(
            "sample",
            "OperatorProbe approves releases.\n- operatorprobe approves releases.\n"
            "The operator. MACHINEPROBE hosts the gateway.",
            ["OperatorProbe", "MachineProbe"],
        )
        self.assertIn("sample: configured private term", findings)

    def test_ci_private_terms_fail_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                privacy_check.private_terms_from_environment()
        with patch.dict(
            os.environ,
            {"HARKLIGHT_PACK_PRIVATE_TERMS": "machine|privatehost"},
            clear=True,
        ):
            self.assertEqual(privacy_check.private_terms_from_environment(), ["privatehost"])
        with patch.dict(
            os.environ,
            {"HARKLIGHT_PACK_PRIVATE_TERMS": "machine|ab"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                privacy_check.private_terms_from_environment()
        with patch.dict(
            os.environ,
            {
                "HARKLIGHT_PACK_PRIVATE_TERMS": (
                    "machine|privatehost\nperson|privateperson\nuser|privateuser"
                )
            },
            clear=True,
        ):
            self.assertEqual(
                privacy_check.private_terms_from_environment(),
                ["privatehost", "privateperson", "privateuser"],
            )

    def test_ci_command_refuses_when_private_terms_are_absent(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            sys, "argv", ["privacy_check.py", "--ci"]
        ):
            self.assertEqual(privacy_check.main(), 2)


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

    def _copied_identity(self, temp: str) -> Path:
        import shutil

        fixture = ROOT / "tests" / "fixtures" / "reference-identity"
        copied = Path(temp) / "identity"
        shutil.copytree(fixture, copied)
        private_terms = Path(temp) / "terms.txt"
        private_terms.write_text("private-sentinel-term\n", encoding="utf-8")
        self.enterContext(
            patch.dict(os.environ, {"HARKLIGHT_PACK_PRIVATE_TERMS_FILE": str(private_terms)})
        )
        return copied

    def test_other_harklight_sources_are_left_out_and_noted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            copied = self._copied_identity(temp)
            (copied / "guidance" / "extra.md").write_text(
                "# Extra\n\nHarklight content is unknown here.\n", encoding="utf-8"
            )
            (copied / "skills" / "other.md").write_text(
                "Harklight notes.\n", encoding="utf-8"
            )
            notes: list[str] = []
            files, _ = sync_from_installation.generate(copied, notes=notes)
        published = "\n".join(files.values())
        self.assertNotIn("unknown here", published)
        self.assertNotIn("Harklight notes", published)
        self.assertEqual(len(notes), 2)

    def test_new_skill_section_passes_with_a_note_unless_auto_merging(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            copied = self._copied_identity(temp)
            skill = copied / "skills" / "harklight-agent" / "SKILL.md"
            text = skill.read_text(encoding="utf-8")
            marker = "## Existing local sender and compatibility route"
            skill.write_text(
                text.replace(marker, "## A new public section\n\nNew text.\n\n" + marker),
                encoding="utf-8",
            )
            with self.assertRaises(sync_from_installation.SyncError):
                sync_from_installation.generate(copied, strict=True)
            notes: list[str] = []
            files, _ = sync_from_installation.generate(copied, strict=False, notes=notes)
        self.assertIn("A new public section", "\n".join(files.values()))
        self.assertEqual(len(notes), 1)
        self.assertIn("new or changed section", notes[0])
        self.assertIn(notes[0], sync_from_installation._pr_body(notes))

    def test_open_pr_fetches_tracking_ref_in_single_branch_clone(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "remote.git"
            seed = root / "seed"
            repo = root / "repo"

            def git(*args: str, cwd: Path = repo) -> str:
                result = subprocess.run(
                    ["git", *args],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise AssertionError("scratch git operation failed")
                return result.stdout.strip()

            def ref_exists() -> bool:
                result = subprocess.run(
                    [
                        "git",
                        "show-ref",
                        "--verify",
                        "--quiet",
                        f"refs/remotes/origin/{sync_from_installation.SYNC_BRANCH}",
                    ],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                return result.returncode == 0

            git("init", "--bare", str(remote), cwd=root)
            git("init", "--initial-branch=main", str(seed), cwd=root)
            git("config", "user.name", "Pack Test", cwd=seed)
            git("config", "user.email", "pack-test", cwd=seed)
            (seed / "pack.txt").write_text("base\n", encoding="utf-8")
            git("add", "pack.txt", cwd=seed)
            git("commit", "-m", "base", cwd=seed)
            git("remote", "add", "origin", str(remote), cwd=seed)
            git("push", "origin", "main", cwd=seed)
            git("checkout", "-b", sync_from_installation.SYNC_BRANCH, cwd=seed)
            (seed / "pack.txt").write_text("open sync\n", encoding="utf-8")
            git("commit", "-am", "open sync", cwd=seed)
            git("push", "origin", sync_from_installation.SYNC_BRANCH, cwd=seed)
            remote_sync = git("rev-parse", "HEAD", cwd=seed)

            git(
                "clone",
                "--single-branch",
                "--branch",
                "main",
                str(remote),
                str(repo),
                cwd=root,
            )
            self.assertEqual(
                git("config", "--get-all", "remote.origin.fetch"),
                "+refs/heads/main:refs/remotes/origin/main",
            )
            self.assertFalse(ref_exists())

            with patch.object(sync_from_installation, "ROOT", repo), patch.object(
                sync_from_installation,
                "_list_sync_prs",
                return_value=[{"number": 2, "url": "", "title": ""}],
            ):
                open_pr_exists, expected_remote = sync_from_installation._open_sync_pr(
                    repo
                )

            self.assertTrue(open_pr_exists)
            self.assertIsNone(expected_remote)
            self.assertTrue(ref_exists())
            self.assertEqual(
                git("branch", "--show-current"), sync_from_installation.SYNC_BRANCH
            )
            self.assertEqual(git("rev-parse", "HEAD"), remote_sync)

    def test_next_sync_rebases_from_main_after_squash_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "remote.git"
            repo = root / "repo"

            def git(*args: str, cwd: Path = repo) -> str:
                result = __import__("subprocess").run(
                    ["git", *args],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise AssertionError("scratch git operation failed")
                return result.stdout.strip()

            git("init", "--bare", str(remote), cwd=root)
            git("init", "--initial-branch=main", str(repo), cwd=root)
            git("config", "user.name", "Pack Test")
            git("config", "user.email", "pack-test" + "@example.invalid")
            (repo / "pack.txt").write_text("base\n", encoding="utf-8")
            git("add", "pack.txt")
            git("commit", "-m", "base")
            git("remote", "add", "origin", str(remote))
            git("push", "-u", "origin", "main")

            git("checkout", "-b", sync_from_installation.SYNC_BRANCH)
            (repo / "pack.txt").write_text("merged pack content\n", encoding="utf-8")
            git("commit", "-am", "first sync")
            git("push", "-u", "origin", sync_from_installation.SYNC_BRANCH)
            stale_sync = git("rev-parse", "HEAD")

            git("checkout", "main")
            (repo / "pack.txt").write_text("merged pack content\n", encoding="utf-8")
            git("commit", "-am", "squash merge")
            git("push", "origin", "main")
            main_tip = git("rev-parse", "HEAD")
            git("checkout", sync_from_installation.SYNC_BRANCH)

            def run_command(args: list[str], cwd: Path | None = None, capture: bool = True) -> str:
                if args[:2] == ["gh", "pr"]:
                    return "[]"
                result = __import__("subprocess").run(
                    args,
                    cwd=cwd or repo,
                    capture_output=capture,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise sync_from_installation.SyncError("scratch git operation failed")
                return result.stdout.strip() if capture else ""

            with patch.object(sync_from_installation, "ROOT", repo), patch.object(
                sync_from_installation, "_run", side_effect=run_command
            ):
                open_pr_exists, expected_remote = sync_from_installation._open_sync_pr(
                    repo
                )
                self.assertFalse(open_pr_exists)
                self.assertEqual(expected_remote, stale_sync)
                self.assertEqual(git("rev-parse", "HEAD"), main_tip)
                (repo / "pack.txt").write_text("next sync content\n", encoding="utf-8")
                git("commit", "-am", "second sync")
                sync_from_installation._push_sync_branch(
                    repo, open_pr_exists, expected_remote
                )

            remote_sync = git(
                "ls-remote", "--heads", "origin", sync_from_installation.SYNC_BRANCH
            ).split()[0]
            self.assertEqual(remote_sync, git("rev-parse", "HEAD"))
            self.assertEqual(
                git("merge-base", "origin/main", sync_from_installation.SYNC_BRANCH),
                main_tip,
            )


class ScratchSyncTests(unittest.TestCase):
    def test_open_pr_updates_in_scratch_clone_and_noops_without_touching_service(
        self,
    ) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "remote.git"
            seed = root / "seed"
            service = root / "service"

            def git(*args: str, cwd: Path = service) -> str:
                result = subprocess.run(
                    ["git", *args],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    raise AssertionError("scratch git operation failed")
                return result.stdout.strip()

            def remote_sync_head() -> str:
                return git(
                    "--git-dir",
                    str(remote),
                    "rev-parse",
                    f"refs/heads/{sync_from_installation.SYNC_BRANCH}",
                    cwd=root,
                )

            git("init", "--bare", str(remote), cwd=root)
            git("init", "--initial-branch=main", str(seed), cwd=root)
            git("config", "user.name", "Pack Test", cwd=seed)
            git("config", "user.email", "pack-test", cwd=seed)
            (seed / "VERSION").write_text("0.1.0\n", encoding="utf-8")
            (seed / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
            (seed / "pack").mkdir()
            (seed / "pack" / "guidance.md").write_text(
                "base guidance\n", encoding="utf-8"
            )
            (seed / "pack" / "elections.json").write_text(
                '{"roles":[]}\n', encoding="utf-8"
            )
            skill = seed / "pack" / "skill" / "harklight-agent"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("generic skill\n", encoding="utf-8")
            git("add", "VERSION", "CHANGELOG.md", "pack", cwd=seed)
            git("commit", "-m", "base", cwd=seed)
            git("remote", "add", "origin", str(remote), cwd=seed)
            git("push", "origin", "main", cwd=seed)

            git("checkout", "-b", sync_from_installation.SYNC_BRANCH, cwd=seed)
            (seed / "VERSION").write_text("0.1.1\n", encoding="utf-8")
            (seed / "CHANGELOG.md").write_text(
                "# Changelog\n\n## v0.1.1\n\nInitial content sync.\n",
                encoding="utf-8",
            )
            (seed / "pack" / "guidance.md").write_text(
                "old guidance\n", encoding="utf-8"
            )
            git("add", "VERSION", "CHANGELOG.md", "pack", cwd=seed)
            git("commit", "-m", "open sync", cwd=seed)
            git("push", "origin", sync_from_installation.SYNC_BRANCH, cwd=seed)
            prior_sync_head = git("rev-parse", "HEAD", cwd=seed)

            git(
                "clone",
                "--single-branch",
                "--branch",
                "main",
                str(remote),
                str(service),
                cwd=root,
            )
            installed_head = git("rev-parse", "HEAD", cwd=service)
            original_guidance = (service / "pack" / "guidance.md").read_text(
                encoding="utf-8"
            )
            files = {
                service / "pack" / "guidance.md": "updated guidance\n",
                service / "pack" / "elections.json": '{"roles":["coder"]}\n',
                service / "pack" / "skill" / "harklight-agent" / "SKILL.md": (
                    "generic updated skill\n"
                ),
            }
            open_pr = [{"number": 2, "url": "", "title": ""}]
            real_run = sync_from_installation._run
            github_commands: list[list[str]] = []

            def run_command(
                args: list[str], cwd: Path | None = None, capture: bool = True
            ) -> str:
                if args[:2] == ["gh", "pr"]:
                    github_commands.append(args)
                    if args[:3] == ["gh", "pr", "list"]:
                        return json.dumps(open_pr)
                    return ""
                return real_run(args, cwd=cwd, capture=capture)

            with (
                patch.object(sync_from_installation, "ROOT", service),
                patch.object(
                    sync_from_installation,
                    "PACK_REPOSITORY_URL",
                    str(remote),
                    create=True,
                ),
                patch.object(
                    sync_from_installation,
                    "_list_sync_prs",
                    return_value=open_pr,
                ) as list_prs,
                patch.object(sync_from_installation, "_run", side_effect=run_command),
            ):
                sync_from_installation._publish(files, [], auto_merge=False)
                updated_sync_head = remote_sync_head()
                self.assertNotEqual(updated_sync_head, prior_sync_head)
                self.assertEqual(
                    git(
                        "--git-dir",
                        str(remote),
                        "rev-parse",
                        f"{updated_sync_head}^",
                        cwd=root,
                    ),
                    prior_sync_head,
                )
                self.assertEqual(
                    git("rev-parse", "HEAD", cwd=service),
                    installed_head,
                    "sync PR staging changed the installed checkout",
                )
                self.assertEqual(git("status", "--porcelain", cwd=service), "")
                self.assertEqual(
                    (service / "pack" / "guidance.md").read_text(encoding="utf-8"),
                    original_guidance,
                )
                self.assertEqual(list_prs.call_count, 2)
                self.assertFalse(
                    any(
                        command[:3] == ["gh", "pr", "create"]
                        for command in github_commands
                    )
                )

                list_prs.reset_mock()
                github_commands.clear()
                sync_from_installation._publish(files, [], auto_merge=False)
                self.assertEqual(remote_sync_head(), updated_sync_head)
                self.assertEqual(list_prs.call_count, 1)
                self.assertFalse(
                    any(
                        command[:3] == ["gh", "pr", "create"]
                        for command in github_commands
                    )
                )

                list_prs.reset_mock()
                private_files = dict(files)
                private_files[service / "pack" / "guidance.md"] = (
                    "private-sentinel-term\n"
                )
                with self.assertRaisesRegex(
                    sync_from_installation.SyncError,
                    "privacy check failed before repository publication",
                ):
                    sync_from_installation._publish(
                        private_files,
                        ["private-sentinel-term"],
                        auto_merge=False,
                    )
                self.assertEqual(remote_sync_head(), updated_sync_head)
                self.assertEqual(git("rev-parse", "HEAD", cwd=service), installed_head)
                self.assertEqual(git("status", "--porcelain", cwd=service), "")


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

    def test_unrelated_manifests_do_not_block_apply_and_a_bad_target_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            identity = Path(temp) / "identity"
            (identity / "guidance").mkdir(parents=True)
            archetypes = identity / "archetypes"
            archetypes.mkdir()
            (archetypes / "coder.toml").write_text(
                'name = "coder"\nskills = ["base"]\n', encoding="utf-8"
            )
            (archetypes / "default.toml").write_text(
                'name = "default"\nskills = ["base"]\n', encoding="utf-8"
            )
            (archetypes / "odd.toml").write_text("not = [valid toml\n", encoding="utf-8")
            (archetypes / "other.toml").write_text('name = "renamed"\n', encoding="utf-8")
            pack = self._make_pack(Path(temp))
            changes = harklight_pack._planned_changes(identity, pack)
            self.assertEqual(
                {kind for kind, _, _ in changes},
                {"skill", "guidance", "manifest:coder", "manifest:default"},
            )

            (archetypes / "coder.toml").write_text('name = "coder"\n', encoding="utf-8")
            with self.assertRaisesRegex(harklight_pack.ApplyError, r"coder\.toml"):
                harklight_pack._planned_changes(identity, pack)

    def test_download_is_retried_once(self) -> None:
        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"ok"

        outcomes = [OSError("timed out"), Response()]

        def fake_urlopen(request: object, timeout: float) -> Response:
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch.object(harklight_pack.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(harklight_pack._request("https://example.test/x"), b"ok")
        outcomes[:] = [OSError("a"), OSError("b")]
        with patch.object(harklight_pack.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(harklight_pack.ApplyError):
                harklight_pack._request("https://example.test/x")

    def test_fresh_identity_can_receive_default_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            identity = Path(temp) / "identity"
            (identity / "guidance").mkdir(parents=True)
            (identity / "archetypes").mkdir(parents=True)
            (identity / "archetypes" / "default.toml").write_text(
                'name = "default"\nskills = []\n', encoding="utf-8"
            )
            changes = harklight_pack._planned_changes(
                identity, self._make_pack(Path(temp))
            )
            guidance = next(content for kind, _, content in changes if kind == "guidance")
        self.assertIn("BEGIN HARKLIGHT FOR TIGHTBEAM v1.2.3", guidance)
        self.assertIn("END HARKLIGHT FOR TIGHTBEAM", guidance)


class ReleaseFetchTests(unittest.TestCase):
    def test_release_targets_the_workflow_commit_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
            (root / "sync-policy.json").write_text(
                '{"publish_policy":"review","release_policy":"manual"}\n',
                encoding="utf-8",
            )
            assets = [root / name for name in ("archive.tgz", "script.py", "sums")]
            commands: list[list[str]] = []
            target = "a" * 40

            def fake_run(args: list[str]) -> str:
                commands.append(args)
                return "main" if args[:3] == ["git", "branch", "--show-current"] else ""

            with (
                patch.object(release_tool, "ROOT", root),
                patch.object(release_tool, "_previous_version", return_value="0.9.0"),
                patch.object(release_tool, "_release_notes", return_value="Release notes."),
                patch.object(release_tool, "private_terms_from_environment", return_value=[]),
                patch.object(release_tool, "scan_repository", return_value=[]),
                patch.object(release_tool, "_build_assets", return_value=tuple(assets)),
                patch.object(release_tool, "_run", side_effect=fake_run),
                patch.dict(
                    os.environ,
                    {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": target},
                ),
            ):
                self.assertEqual(release_tool.main(), 0)

            release_command = next(command for command in commands if command[:3] == ["gh", "release", "create"])
            self.assertEqual(release_command[release_command.index("--target") + 1], target)

    def test_push_does_not_publish_with_manual_release_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
            (root / "sync-policy.json").write_text(
                '{"publish_policy":"review","release_policy":"manual"}\n',
                encoding="utf-8",
            )
            with (
                patch.object(release_tool, "ROOT", root),
                patch.object(release_tool, "_previous_version", return_value="0.9.0"),
                patch.object(release_tool, "_release_notes", return_value="Release notes."),
                patch.object(release_tool, "private_terms_from_environment", return_value=[]),
                patch.object(release_tool, "scan_repository", return_value=[]),
                patch.object(release_tool, "_build_assets") as build_assets,
                patch.dict(os.environ, {"GITHUB_EVENT_NAME": "push"}),
            ):
                self.assertEqual(release_tool.main(), 0)
            build_assets.assert_not_called()

    def test_release_without_changelog_entry_uses_default_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
            with patch.object(release_tool, "ROOT", root):
                self.assertEqual(
                    release_tool._release_notes("1.0.0"),
                    "Harklight for Tightbeam v1.0.0\n",
                )

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
