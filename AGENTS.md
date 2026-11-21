# Harklight for Tightbeam pack repository guidance

## CI, small changes, and releases

- Keep changes small and independently reviewable. Merge passing PRs to `main` promptly while the pack remains usable. If `main` turns red, fix or revert the change that caused it before stacking more work on it; do not hold an unrelated fix behind unfinished work without a real dependency.
- Preserve the existing CI. Pull requests from this repository and pushes to `main` run the privacy check (`python3 tools/privacy_check.py --ci`) and the unit tests (`python3 -m unittest discover -s tests -v`); pull requests from forks run the privacy check only, so run the tests locally for them. Read the integrated `main` result; a pre-merge pass is not that result. Run the tests locally with a scratch `HOME`.
- Unfinished behavior ships disabled by default, and the disabled default must stop the behavior itself. Do not add a feature flag framework; use the existing `sync-policy.json` settings when a policy switch is needed.
- A merge to `main` that raises `VERSION` (with its `CHANGELOG.md` entry) publishes a versioned release while `release_policy` is `auto`; a merge that leaves `VERSION` alone publishes nothing. Treat raising `VERSION` as a release action.
- Every published release must state its protocol compatibility: protocol 0.1 (old) or protocol 0.2 (new), plus the compatible Harklight Server, app, web and agent versions. Use the coordinated release plan and verified evidence; distinguish unverified combinations instead of implying compatibility.
- Move to protocol 0.2 with the coordinated 0.2.0 release, including the agent. Treat the transition as a replacement: remove old protocol handling without compatibility paths or shims, and limit protocol 0.1 work to keeping the current installation working until cut-over.
- Keep public text free of machine names, user ids and secrets; the privacy check enforces this.
