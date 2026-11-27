# Changelog

## v0.2.2

The pack now teaches native Tightbeam FYI and requests, acknowledgment and
same-thread replies and results, and settlement by the original operation ID.
It corrects feed recovery guidance for Agent 0.2.3 and retains the separate
standalone Agent procedures. The archive contains the skill, guidance,
elections, and installer distribution. Relay files are excluded.

This release uses Harklight protocol 0.2 only. The general pack component
target is Server 0.2.x, Agent 0.2.6 or later in the 0.2 series, and Web 0.2.5
or later in the 0.2 series when using the web client. iOS compatibility is
unverified.

Compatible with Tightbeam: None verified.

Native FYI, same-thread Chat and Seen, acknowledgment, reply and result
were checked on Tightbeam 0.1.17+5505 with Agent 0.2.3 and Server 0.2.20.
Isolated ordinary commands were exercised with Server 0.2.19. These checks
cover the native command paths and do not establish exact-release pack
installation compatibility.

### Breaking changes

The managed wake instructions now require Tightbeam's native Harklight
read, acknowledge, reply and result commands. Use guidance matched to the
installed Tightbeam version if those commands are unavailable. No installer
interface or default activation behavior changed.

## v0.2.1

Clarifies inline attachment guidance for external agents. Progress updates
still preserve existing attachments when the file list is omitted.

This release uses Harklight protocol 0.2 only. It supports Harklight Server
0.2.x, Agent 0.2.6 or later in the 0.2 series, and Web 0.2.5 or later in the
0.2 series when using the web client. It requires Tightbeam's protocol 0.2
Harklight integration. iOS release compatibility is unverified.

## v0.2.0

The pack now uses Harklight protocol 0.2 only. It documents the current
Tightbeam send and wake lifecycle, Progress, replies, and handoffs. It drops
the old message selectors and the migrated enrollment-port workaround.
Applying the pack updates Tightbeam guidance and skill elections. It leaves
Harklight messages and attachments in their existing store.

Compatibility: Harklight Server 0.2.x (current deployment: 0.2.19), Agent
0.2.6 or later in the 0.2 series, and Web 0.2.5 or later in the 0.2 series
when using the web client. Requires Tightbeam's protocol 0.2 Harklight
integration. iOS release compatibility has not been verified.

## v0.1.3

Apply now ignores unrelated archetype manifests and retries a failed download once. Manifests that apply edits still require a valid format and matching name.

Reference sync reports source-shape changes for human review while retaining checks that prevent private sections from being published. Privacy checks accept public attribution and documentation examples while retaining private-name and non-public-address checks.

Release publication now follows versioned merges to main. Generated sync pull requests still require human review.

The skill documents revise/retract by session handle and settle by operation key for messages without a local send record, plus warnings for unresolved supersede targets. These command behaviors require the Tightbeam changes merged in PR #874; older installations may not support them.

Compatibility: prior v0.1.2 apply/update evidence covered Tightbeam v0.1.16+4283 using checksum-verified archives via --source-dir. That is not v0.1.3 runtime verification. The default online update path and the new command behaviors against a real Harklight Agent have not been verified end-to-end. No new runtime compatibility claim is made for this release.

## v0.1.2

Refreshed the Harklight skill from the allowlisted reference identity.

## v0.1.1

Keep sync staging in a temporary clone so scheduled updates do not move the installed checkout.

## v0.1.0

Refreshed the Harklight skill and operator guidance from the allowlisted reference identity.


Changes to the versioned Harklight for Tightbeam pack.
