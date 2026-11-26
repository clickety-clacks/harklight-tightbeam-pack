"""Offline checks for the runtime compatibility matrix.

These cover release selection and fail-closed behavior. The real runtime check,
which boots published Tightbeam releases, runs in the runtime compatibility
workflow.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import runtime_compat as rc


def _release(tag: str, published: str, *, draft: bool = False, prerelease: bool = False, assets=None):
    version = tag.removeprefix("v").split("+", 1)[0]
    if assets is None:
        assets = [
            {"name": f"tightbeam-{version}-linux-x86_64-abc1234.tgz", "browser_download_url": "p"},
            {"name": f"tightbeam-{version}-darwin-aarch64-abc1234.tgz", "browser_download_url": "d"},
            {"name": "SHA256SUMS", "browser_download_url": "s"},
            {"name": "release-provenance.json", "browser_download_url": "r"},
        ]
    return {
        "tag_name": tag,
        "published_at": published,
        "draft": draft,
        "prerelease": prerelease,
        "assets": assets,
    }


RELEASES = [
    _release("v0.1.17+5000", "2026-11-20T00:00:00Z", prerelease=True),
    _release("v0.1.18+5100", "2026-11-21T00:00:00Z", draft=True),
    _release("v0.1.16+4304", "2026-11-18T00:48:07Z"),
    _release("v0.1.15+4082", "2026-11-15T11:46:29Z"),
    _release("v0.1.14+3724", "2026-11-06T17:05:12Z"),
]


class SelectWindowTests(unittest.TestCase):
    def test_selects_current_and_previous_full_releases_with_exact_tags(self) -> None:
        window = rc.select_window(RELEASES, "v0.1.16+4304")
        self.assertEqual([release.tag for release in window], ["v0.1.16+4304", "v0.1.15+4082"])
        self.assertEqual(window[0].package["name"], "tightbeam-0.1.16-linux-x86_64-abc1234.tgz")

    def test_refuses_when_newest_full_release_is_not_latest(self) -> None:
        with self.assertRaisesRegex(rc.RuntimeCompatError, "not the latest"):
            rc.select_window(RELEASES, "v0.1.15+4082")

    def test_refuses_fewer_than_two_full_releases(self) -> None:
        with self.assertRaisesRegex(rc.RuntimeCompatError, "fewer than two"):
            rc.select_window(RELEASES[:3], "v0.1.16+4304")

    def test_refuses_missing_package_or_sidecar(self) -> None:
        broken = [dict(RELEASES[2], assets=RELEASES[2]["assets"][1:]), RELEASES[3]]
        with self.assertRaisesRegex(rc.RuntimeCompatError, "Linux x86_64 package"):
            rc.select_window(broken, "v0.1.16+4304")
        no_sums = [
            dict(RELEASES[2], assets=[a for a in RELEASES[2]["assets"] if a["name"] != "SHA256SUMS"]),
            RELEASES[3],
        ]
        with self.assertRaisesRegex(rc.RuntimeCompatError, "SHA256SUMS"):
            rc.select_window(no_sums, "v0.1.16+4304")

    def test_refuses_unexpected_tag_or_tied_publication(self) -> None:
        with self.assertRaisesRegex(rc.RuntimeCompatError, "unexpected tag"):
            rc.select_window([_release("latest", "2026-11-19T00:00:00Z"), *RELEASES], "latest")
        tied = [RELEASES[2], dict(RELEASES[3], published_at=RELEASES[2]["published_at"])]
        with self.assertRaisesRegex(rc.RuntimeCompatError, "ambiguous"):
            rc.select_window(tied, "v0.1.16+4304")


class VerificationTests(unittest.TestCase):
    NAME = "tightbeam-0.1.16-linux-x86_64-1ca470a.tgz"

    def test_checksum_entry_must_be_single_and_valid(self) -> None:
        digest = "a" * 64
        self.assertEqual(rc.expected_digest(f"{digest}  {self.NAME}\n", self.NAME), digest)
        self.assertEqual(rc.expected_digest(f"{digest} *{self.NAME}\n", self.NAME), digest)
        for sums in ("", f"{'z' * 64}  {self.NAME}", f"{digest}  {self.NAME}\n{digest}  {self.NAME}"):
            with self.assertRaises(rc.RuntimeCompatError):
                rc.expected_digest(sums, self.NAME)

    def test_provenance_must_name_tag_commit_and_asset(self) -> None:
        good = {
            "repository": rc.TIGHTBEAM_REPOSITORY,
            "tag": "v0.1.16+4304",
            "commit": "1ca470a68ce7e1dc7f3a4c05fc42f4bd7c9cc495",
            "assets": [self.NAME],
        }
        rc.verify_provenance(good, "v0.1.16+4304", self.NAME)
        for change in (
            {"tag": "v0.1.16+4283"},
            {"repository": "someone/else"},
            {"commit": "0" * 40},
            {"assets": []},
        ):
            with self.assertRaises(rc.RuntimeCompatError):
                rc.verify_provenance({**good, **change}, "v0.1.16+4304", self.NAME)


class FailClosedTests(unittest.TestCase):
    def test_refuses_to_boot_gateways_outside_ci_without_isolation(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(rc.RuntimeCompatError, "boots real gateways"):
                rc.tested_versions(ROOT)

    def test_returns_sorted_tags_only_after_both_pass(self) -> None:
        window = rc.select_window(RELEASES, "v0.1.16+4304")
        with (
            patch.object(rc, "_require_isolated_host"),
            patch.object(rc, "discover", return_value=window),
            patch.object(rc, "_check_release") as check,
        ):
            self.assertEqual(rc.tested_versions(ROOT), ("v0.1.15+4082", "v0.1.16+4304"))
            self.assertEqual(check.call_count, 2)

    def test_any_failed_case_raises_instead_of_returning_fewer_versions(self) -> None:
        window = rc.select_window(RELEASES, "v0.1.16+4304")
        for failure in (rc.RuntimeCompatError("apply failed"), OSError("disk"), KeyError("x")):
            calls = [None, failure]

            def check(*_args, calls=calls):
                outcome = calls.pop(0)
                if outcome is not None:
                    raise outcome

            with (
                patch.object(rc, "_require_isolated_host"),
                patch.object(rc, "discover", return_value=window),
                patch.object(rc, "_check_release", side_effect=check),
            ):
                with self.assertRaisesRegex(rc.RuntimeCompatError, r"^v0\.1\.15\+4082: "):
                    rc.tested_versions(ROOT)

    def test_discovery_failure_propagates(self) -> None:
        with (
            patch.object(rc, "_require_isolated_host"),
            patch.object(rc, "_get", side_effect=rc.RuntimeCompatError("download failed")),
        ):
            with self.assertRaises(rc.RuntimeCompatError):
                rc.tested_versions(ROOT)


class CheckAppliedTests(unittest.TestCase):
    def _identity(self, temp: Path, *, skill: str | None = None, guidance: str | None = None) -> Path:
        identity = temp / "identity"
        (identity / "skills" / rc.SKILL_NAME).mkdir(parents=True)
        (identity / "guidance").mkdir()
        (identity / "archetypes").mkdir()
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        pack_skill = (ROOT / "pack" / "skill" / rc.SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")
        pack_guidance = (ROOT / "pack" / "guidance.md").read_text(encoding="utf-8")
        (identity / "skills" / rc.SKILL_NAME / "SKILL.md").write_text(
            pack_skill if skill is None else skill, encoding="utf-8"
        )
        block = (
            rc.GUIDANCE_BEGIN.format(version=version) + "\n" + pack_guidance.strip() + "\n" + rc.GUIDANCE_END
        )
        (identity / "guidance" / "default.md").write_text(
            "Org guidance.\n\n" + (block if guidance is None else guidance) + "\n", encoding="utf-8"
        )
        for role in ("default", "coder"):
            (identity / "archetypes" / f"{role}.toml").write_text(
                f'name = "{role}"\n{rc.ELECTION_MARKER}\nskills = ["other", "{rc.SKILL_NAME}"]\n',
                encoding="utf-8",
            )
        (identity / "archetypes" / "outsider.toml").write_text(
            'name = "outsider"\nskills = []\n', encoding="utf-8"
        )
        return identity

    def test_accepts_a_complete_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            rc.check_applied(self._identity(Path(temp)), ROOT)

    def test_rejects_wrong_skill_missing_guidance_or_election(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(rc.RuntimeCompatError, "skill"):
                rc.check_applied(self._identity(Path(temp), skill="other"), ROOT)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(rc.RuntimeCompatError, "guidance"):
                rc.check_applied(self._identity(Path(temp), guidance=""), ROOT)
        with tempfile.TemporaryDirectory() as temp:
            identity = self._identity(Path(temp))
            (identity / "archetypes" / "coder.toml").write_text(
                'name = "coder"\nskills = []\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(rc.RuntimeCompatError, "coder"):
                rc.check_applied(identity, ROOT)
        with tempfile.TemporaryDirectory() as temp:
            identity = self._identity(Path(temp))
            (identity / "archetypes" / "outsider.toml").write_text(
                f'name = "outsider"\nskills = ["{rc.SKILL_NAME}"]\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(rc.RuntimeCompatError, "outsider"):
                rc.check_applied(identity, ROOT)


if __name__ == "__main__":
    unittest.main()
