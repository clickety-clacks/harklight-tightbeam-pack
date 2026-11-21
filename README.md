# Harklight for Tightbeam

A versioned guidance pack for Tightbeam organizations that use the
engineering-kungfu bundle. It adds the Harklight Agent skill, elects that skill
for the roles used by the reference installation, and adds a marked guidance
section for reaching the operator through Harklight.

The pack works with local or hosted Harklight. Harklight connection settings
stay in each organization's own Tightbeam configuration.

## Protocol compatibility

The source on this branch targets protocol 0.2 with Harklight Server, Agent,
app and web 0.2.x and the paired Tightbeam Harklight integration. It is not
compatible with protocol 0.1. Published v0.1.3 remains the old-protocol release;
the source migration does not change that release or authorize a live update.

The Agent command interface is pinned to source
[d3fe268](https://github.com/clickety-clacks/harklight-agent/commit/d3fe2689955eb07eb875565fe168f6686ee0777e).
Server field semantics come from [#256](https://github.com/clickety-clacks/harklight-server/pull/256)
at `2ecf51f` and [#270](https://github.com/clickety-clacks/harklight-server/pull/270)
at `3511371`, including the attachment-preservation ruling. These are integration
development references, not released deployment versions. Isolated paired
verification at Agent `d3fe268` and Server `04e7b806` passed Progress attachment
preservation, lost-response recovery and concurrent feeds. That Server predates
the final upload-discard patch, so those results do not establish discard acceptance.
Before the 0.2 pack release, confirm the Tightbeam interface and remaining paired acceptance,
review the generated content, and name exact compatible versions in release notes.

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
