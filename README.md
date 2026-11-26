# Harklight for Tightbeam

A versioned guidance pack for Tightbeam organizations that use the
engineering-kungfu bundle. It adds the Harklight Agent skill, elects that skill
for the roles used by the reference installation, and adds a marked guidance
section for reaching the operator through Harklight.

The pack works with local or hosted Harklight. Harklight connection settings
stay in each organization's own Tightbeam configuration.

## Protocol compatibility

Pack 0.2 uses Harklight protocol 0.2 only. Use Harklight Server 0.2.x
(current deployment: 0.2.19), Agent 0.2.6 or later in the 0.2 series, and,
if using the web client, Web 0.2.5 or later in the 0.2 series. Tightbeam
requires its matching protocol 0.2 integration. iOS release compatibility
has not been verified.

The source targets are Agent
[`5771877`](https://github.com/clickety-clacks/harklight-agent/commit/5771877daa1c3073c71ec7958802742a26ec90f5)
and Tightbeam [PR #886](https://github.com/clickety-clacks/tightbeam/pull/886)
at `5cba4761ddcd19204a4495afe423b4cf47a98a08`. The Agent has the same source tree
as the command-contract build `95bf687`. Server field semantics follow
[#256](https://github.com/clickety-clacks/harklight-server/pull/256),
[#270](https://github.com/clickety-clacks/harklight-server/pull/270) and the
round 26 projection-error behavior in
[#289](https://github.com/clickety-clacks/harklight-server/pull/289).
These are source references, not released deployment versions.

Independent review of the pinned Tightbeam source is clean. Its isolated
three-component run with Agent `5771877` and Server
`1dc7ecbe0fa6e8239d9aef659116bc8e942ec164` passed real batch and SSE internal
fault pause/resume, exact settlement after a committed revision whose response
failed, and automatic recovery after a SQLite storage refusal. This is scoped
integration evidence, not final release acceptance or live-install approval.

Earlier component runs verified that inline attachment bytes survive Progress
settlement, chat and answer wakes, post-dispatch receipts, and feed restart. New revisions can issue new inline
download IDs. The saved-receipt recovery after a worker stops before journaling
has independent source review and isolated fixture tests; it was not one of the
four real-Server fault cases above.

The Server [#320](https://github.com/clickety-clacks/harklight-server/pull/320)
follow-up was exercised separately on pre-candidate Server
`d4d94b686a8e1c55c3ad2e22dba326d30ad21fcc` and CI-packaged Agent 0.2.0
`85bcd191258b7e90230a80def88aa677fbc0397a`. All 20 targeted checks passed:
item receipt and result return `409 not_answered` before an answer, and
`400 unsupported` after a separately registered Agent answers. Replaying each
refusal preserves its Request-Id. A distinct person answer permits both.
These checks extend the receipt/result instructions below; they do not replace
the earlier fault-test evidence or establish final candidate acceptance.

## Apply or update

Run this command on the organization's Tightbeam gateway host, where the
identity directory is available and an authorized administrator CLI session is
active:

~~~~sh
curl -fsSL https://github.com/clickety-clacks/harklight-tightbeam-pack/releases/latest/download/harklight-pack.py | python3 - apply
~~~~

Run the same command with update to fetch and apply the newest version:

~~~~sh
curl -fsSL https://github.com/clickety-clacks/harklight-tightbeam-pack/releases/latest/download/harklight-pack.py | python3 - update
~~~~

The command uses the public Tightbeam identity-edit CLI. It updates only the
pack's skill, its marked guidance section, and the skill elections it manages.
Existing organization edits outside those areas remain in place. Re-running an
apply or update makes no further changes. If the identity directory cannot be
read locally, the CLI is unavailable, or a source format is unfamiliar, the
command stops before applying that part.

The identity directory is selected by TIGHTBEAM_IDENTITY_DIR, or from the
active Tightbeam base directory when it is not set. Do not point it at a
production organization for a trial run.

## Automatic reference sync

The sync job reads only the allowlisted skill, guidance sections, and
archetype manifests from the configured identity directory. It changes this
repository's generated pack files and opens a pull request only after the
source-shape and privacy checks pass. It does not write to the source
installation.

The sample user service and timer are in systemd/user. They are not enabled
by the repository. The timer is daily at 04:00 UTC. Configure a private
terms file outside this repository before enabling sync; it may contain
organization-only names and addresses and must never be committed.
The service account also needs read access to the reference identity and a
GitHub CLI login with push access to this repository. Keep that login outside
the repository and configure Git to use the GitHub CLI credential helper.

The default publish policy is review: sync opens a pull request and waits.
Set publish_policy to auto_merge_clean in sync-policy.json only after
automatic sync-PR merging has been chosen. Release publication has a separate
release_policy: it is auto, so a push to main that raises VERSION publishes the
release. A release workflow dispatch on main also publishes the current
version. Setting release_policy to manual stops publication from a push. Both
paths run the same privacy checks.

The support window is the current full Tightbeam release and the preceding
full release. Publication runs the pack against both exact published builds.
Each version's changelog entry needs a `Compatible with Tightbeam:` line
matching the two tested versions in lexicographic order. Use
`Compatible with Tightbeam: From release tests.` to fill the line from CI.
Fixture-only unit tests do not count. Outside this window, the installer checks the CLI's
identity-edit capabilities before attempting writes.

Include a `### Breaking changes` section. The publication step detects removed
or renamed installer actions, flags, literal output prefixes, and environment
keys, plus removed verified Tightbeam versions. An independent repository
reviewer checks those signals and semantic changes such as flag behavior or
response meaning. They approve the final release PR head in GitHub with
`Breaking changes confirmed.` on its own line in the approval. Publication
requires that approval and checks that the merged version and changelog
match the reviewed files. If approval is missing, approve the exact release
PR and rerun the failed release workflow.

## Privacy checks

Configure the repository Actions secret HARKLIGHT_PACK_PRIVATE_TERMS before
opening sync pull requests. Store one categorized term per line, such as
machine|<private-machine-name>, person|<private-person-name>, and
user|<private-user-id>; add email, hostname, path, or other categories when
they apply. The checker fails closed when the secret is missing or malformed.
Keep the values out of repository files,
workflow output, pull request text, and release notes. For a local
pre-publication check, point HARKLIGHT_PACK_PRIVATE_TERMS_FILE at a private
file containing one term per line. Fork pull requests are scanned by the
trusted base-branch workflow, which reads their files as data without running
their code or exposing the private-term secret to it.

## Development

Python 3.11 or newer is required. Run the focused checks with:

~~~~sh
python3 -m unittest discover -s tests -v
HARKLIGHT_PACK_PRIVATE_TERMS_FILE=/path/to/private-terms.txt python3 tools/privacy_check.py
~~~~

The release workflow creates a versioned archive after a reviewed change
raises VERSION and is merged to main. Release notes and assets
pass the privacy check before publication.

## License

MIT. See LICENSE.
