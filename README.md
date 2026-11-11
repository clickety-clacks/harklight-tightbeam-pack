# Harklight for Tightbeam

A versioned guidance pack for Tightbeam organizations that use the
engineering-kungfu bundle. It adds the Harklight Agent skill, elects that skill
for the roles used by the reference installation, and adds a marked guidance
section for reaching the operator through Harklight.

The pack works with local or hosted Harklight. Harklight connection settings
stay in each organization's own Tightbeam configuration.

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

The default publish policy is review: sync opens a pull request and waits.
Set publish_policy to auto_merge_clean in sync-policy.json only when
automatic merge and release have been chosen for the repository. Both policies
run the same privacy checks.

## Development

Python 3.11 or newer is required. Run the focused checks with:

~~~~sh
python3 -m unittest discover -s tests -v
python3 tools/privacy_check.py --ci
~~~~

The release workflow publishes a versioned archive when a reviewed change
updates VERSION. Release notes and assets pass the privacy check before
publication.

## License

MIT. See LICENSE.
