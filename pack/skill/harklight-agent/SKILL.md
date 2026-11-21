---
name: harklight-agent
description: Send authorized Harklight notices, decisions, or questions from Tightbeam and handle replies or chat using protocol 0.2. Use for Harklight communication, including from remote hosts.
---

<!-- HARKLIGHT_PACK_MANAGED -->

# Harklight for Tightbeam agents

This skill targets protocol 0.2: Harklight Server, Agent, app and web 0.2.x,
with the matching Tightbeam Harklight integration. It does not support protocol
0.1. Use the organization's configured enrollment and the installed help for
its execution context.

The raw Agent commands below are pinned to the published 0.2 command contract.
The Tightbeam-facing argv, response casing, send bindings and wake/settle
behavior describe the paired integration design and remain proposed until its
implemented consumer is read back. They are not evidence that an installed
Tightbeam already supports them. Use the verified Agent interface for source
integration work; confirm the Tightbeam interface before publishing this pack.

## Automatic lifecycle for your own messages

Send through `tightbeam harklight-send` from your authenticated Tightbeam
session. A committed registered send opens automatic wake delivery. Retain its
server item ID, conversation handle, sender and operation ID. A conversation
handle is not a Tightbeam session key. End the turn and handle the resulting
wake; no polling or separate waiter is needed.

Tightbeam owns its wake routing and handoff receipts. Other readers may open
the same filtered feed concurrently. There is no exclusive listener, takeover,
cover or attach operation. A terminal answer does not close the conversation:
chat replies can continue after an answer or retraction when a conversation
exists. A raw feed does not replace Tightbeam's registered routing.

A committed revision keeps the subscription on the same item. A committed
retraction ends future wakes for that item. Preserve any pre-commit delivery
marker on an entry that arrives later; retraction does not undo prior effects.
Only a confirmed commit establishes the corresponding wake effect.

## Configuration and sending

Use the configuration established for the command's execution context. Raw
Agent commands and the gateway need not share an identity directory, CA,
endpoint or journal. Preserve an actual failure for the service owner; do not
copy credentials or change live configuration to make an example work.

Agent 0.2 uses the enrolled device endpoint. For a migrated identity whose saved
port still points to enrollment, its configured device port can be selected
with `--device-port` or `HARKLIGHT_DEVICE_PORT`. New enrollments store device
and enrollment ports separately. Do not infer one port from another.

Send a question through Tightbeam:

```sh
tightbeam harklight-send --session new --sender-id "$HARKLIGHT_SENDER" \
  --title "Product: choose the next step" \
  --body "Select an option or write a note." \
  --choices-json '["Proceed", "Defer"]'
```

Use the sender already granted to the enrollment. Keep the returned
`messageId`, `handle`, `senderId` and `opId` when present. The server issues the
item ID; an uncertain send can lack it. Preserve the operation ID instead of
inventing an item ID. Inspect the outcome and wake effect before claiming the
message was sent.

Choose structured choices for decisions, text for open questions and Seen for
informational updates. Opening a message is not Seen or an answer. Put the
product in the title when sharing a sender. Tightbeam's Progress send/update
interface belongs to its paired integration; raw Agent flags are not automatically
Tightbeam flags. Use only options exposed by that installed integration.

Tightbeam's `--files-json` accepts file paths. Raw Agent reply uses `--file`
for a path or `--file-id` for an upload handle. Preserve failed attachments
rather than silently dropping them.

## Revise, retract or supersede

Revise an existing item with its actual current content revision:

```sh
tightbeam harklight-revise --message "$HARKLIGHT_ITEM" \
  --base-revision "$HARKLIGHT_REVISION" --title "Product: updated request" \
  --body "The revised details."
```

To withdraw an obsolete request, use retraction. It withdraws the item and ends
its future wakes; it is a separate action from revision:

```sh
tightbeam harklight-retract --message "$HARKLIGHT_ITEM"
```

Use the Tightbeam lifecycle commands for registered items so its wake effects
remain associated with the operation. Raw Agent writes do not complete that
association. Do not turn a refusal into an implicit replacement request.

To replace requests, repeat `--supersedes` on a new Tightbeam send. Read every
per-target result: only targets actually superseded get the corresponding wake
effect. Targets belong to the same enrolled agent and sender; duplicates are
considered once in input order. Warnings `invalid`, `unknown` and `closed`
leave those targets unchanged. A different Tightbeam session can remain the
registered recipient; do not infer ownership from the caller.

For pre-cutover references, retain the original sender and old message ID. The
Agent CLI resolves that pair to the opaque server item ID through protocol 0.2.
An explicit legacy Progress lookup with no match returns `404 not_found`
and exit 2; it must not select another item. Raw Agent `--supersedes` takes item IDs; `--supersedes-local` explicitly resolves
a local reference by sender. Keep Tightbeam's existing association without a
second mapping or old transport fallback.

Raw Agent revision can optionally correlate to a person chat entry on the item
at its current request revision. Success returns the message and acted entry;
wrong item or kind returns `404 not_found`, and an earlier-revision turn returns
`409 stale_request`. Preserve the exact entry ID during recovery.

For a raw Agent Progress update, use the actual conversation handle and item:

```sh
harklight-agent progress --session "$HARKLIGHT_HANDLE" \
  --request "$HARKLIGHT_ITEM" --percent 50 --stage "Verification"
```

Progress reads the content, revision and attachment metadata together. Its
conditional PUT changes Progress while carrying the other message fields and
omitting `file_ids`: the Server preserves the matched revision's attachments,
including migrated inline files. Exact replay preserves both that omission and
`If-Match`. Do not rebase a pending write onto a newer revision.

For raw general revision, `--clear-files` sends an empty list and clears the
attachments. A nonempty `--file-id` list replaces the entire set and may mix
new upload handles with download IDs already attached to that same item.
Other writes taking file IDs require upload handles. A stale revision returns
412; a terminal item refuses revision/retraction with `already_closed`, or
`already_retracted` when retracted.

## Read results and settle an uncertain write

Distinguish committed, refused and uncertain operations. Keep the original
operation key, finalized payload, correlation entry, base revision and file
semantics. A successful replay returns the stored success. A failed precondition
is not authority to prepare a new write against newer content.

Use `tightbeam harklight-settle` for an unresolved Tightbeam operation, selecting
it with the identifiers supported by the installed integration. An uncertain
send without a server item ID must remain associated with its operation ID.
Do not substitute raw Agent retry for Tightbeam settlement: a raw success does
not finish Tightbeam's item binding or wake effects.

Before the raw write, read and retain its journal identity from the same
execution context:

```sh
harklight-agent journal-id
```

Retain the returned `journal_id` alongside the operation ID. To recover that
raw operation, qualify retry with the original journal ID, particularly when
an absence result would affect your next action:

```sh
harklight-agent retry --op-id "$HARKLIGHT_OP_ID" \
  --journal-id "$HARKLIGHT_JOURNAL_ID"
```

Do not substitute an ID read from a replacement journal after a failure.

Exit 0 confirms success; 1 is a local setup/journal/operation conflict; 2 is a
definite Server refusal; 5 means unsupported; 7 means unresolved or retryable.
Read the structured outcome and stderr reason, not just the exit code. A
successful HTTP response that fails validation leaves the write unresolved
under its original operation key. On a rejected or uncertain Server response,
`request_id`, when present, is the Server Request-Id; a successful send's
`request_id` is its local operation reference matching `op_id`. Preserve that
distinction when reporting a failure. Preserve
a pending intent when its journal is unavailable or mismatched. Only an intact,
matching journal's `operation_absent` establishes that it has no such intent;
`operation_unresolved` does not. Abandoning local recovery cannot undo a Server
write. Do not use a new send to discover whether an old send committed.

## Read one of your own sent messages

```sh
harklight-agent message-get --item-id "$HARKLIGHT_ITEM"
harklight-agent message-get --item-id "$HARKLIGHT_ITEM" --revision 2
harklight-agent message-entries --item-id "$HARKLIGHT_ITEM" --limit 50
```

The current read returns `{rev,message}`; a historical read returns
`{rev,revision:{request_revision,message,files}}`. An unavailable historical
revision returns `404 not_found`. Content revision, resource version, feed
position and immutable entry position serve different purposes. A read does
not mean Seen, handed or acted. To resolve a migrated reference, use
`message-get --sender-id NAME --message-id OLD_ID`.

`FileCreated.file_id` is an upload handle for writes/discard. `FileRef.file_id`
on attached content is the download ID; downloading by upload handle fails.
Revise's same-item reuse is the specific exception described above.

## Handle a delivered change

Read the wake's actual item, handle, entry and revision identities. A chat
change carries a real entry ID. An answer or close-out is a message change
with a terminal, not a synthetic conversation entry. Preserve the raw answer,
including explicit JSON null. Never use a feed revision as a reply target.
A repeated terminal with the same item, state and timestamp is the same
occurrence even when a later message revision includes it.

The Server records delivery when serving a chat entry or terminal answer.
Tightbeam records handed after its durable prompt-dispatched boundary. Read
that outcome; a receipt does not prove the requested action happened. For an
authorized standalone handoff or recovery, choose the receipt for the actual delivered
change. For a person chat entry:

```sh
harklight-agent receipt --item-id "$HARKLIGHT_ITEM" --entry-id "$HARKLIGHT_ENTRY"
```

For an answer, which has no conversation entry ID, use the item receipt instead:

```sh
harklight-agent receipt --item-id "$HARKLIGHT_ITEM"
```

These are alternative targets, not a sequence to run for one handoff. Preserve
`--agent` and `--rerouted` attribution where applicable. `--not-handed REASON` supplies the required reason for failed handoff. Read `response.status` (`recorded`, `already_recorded`, `superseded`)
and effective `stage_outcome`. A handed outcome stays handed; a not-handed
outcome may advance to handed. Delivery is nested in the entry or terminal,
not a top-level message flag.

Reply to a person chat in its existing conversation:

```sh
harklight-agent reply --item-id "$HARKLIGHT_ITEM" \
  --in-reply-to "$HARKLIGHT_ENTRY" --body "The request is complete."
```

Use the actual outcome as the body. Correlation requires a person chat turn on
that item at its current request revision. The first correlated reply marks it
acted; further replies are legal. An uncorrelated reply is an ordinary agent
turn. A reply may contain only files: omit `--body` and pass `--file PATH`.
Conversation discussion is not itself new authority.

For an answered terminal, reconcile earlier effects before acting and report
the actual result:

```sh
harklight-agent result --item-id "$HARKLIGHT_ITEM" --status applied
```

Use `applied` only for an established effect, `refused` when it cannot be applied,
or `received` while unresolved. The reference derives from the operation; no
explicit result reference or conversation entry ID is supplied. A sessionless
answer remains visible but answer handoff/result returns `400 unsupported`.
A session-bound item without an answer returns `409 not_answered`; a final or
incompatible result returns `409 already_closed`. Cleared, expired or superseded
outcomes stop work on that request and are not approval.

Report each file's actual transfer and use independently of handoff:

```sh
harklight-agent file-get --file-id "$HARKLIGHT_FILE" --output "$HARKLIGHT_PATH"
```

After the download succeeds, report the transfer:

```sh
harklight-agent file-use --item-id "$HARKLIGHT_ITEM" \
  --entry-id "$HARKLIGHT_ENTRY" --file-id "$HARKLIGHT_FILE" --transferred
```

After actually using that file, report use separately:

```sh
harklight-agent file-use --item-id "$HARKLIGHT_ITEM" \
  --entry-id "$HARKLIGHT_ENTRY" --file-id "$HARKLIGHT_FILE" --used
```

The file must belong to that delivered turn. Use `--not-transferred --reason`
for a failed transfer, or `--unusable --reason` for failed use. Successful-only
reports omit the reason; when both dimensions fail in one write its reason
applies to both. An identical report is a duplicate. A conflict in either
outcome or reason refuses the whole write. A later use report can follow a
failed transfer without rewriting that transfer. Downloading does not prove use.

## Raw command recovery and references

Tightbeam's feed handles its automatic wake routing. For standalone reading:

```sh
harklight-agent read --session "$HARKLIGHT_HANDLE" --snapshot
harklight-agent listen --session "$HARKLIGHT_HANDLE" --after "$HARKLIGHT_REV" --follow
```

Durable change kinds are `message`, `entry` and `advisory`. Focus is ephemeral.
Multiple readers can use one scope. The default reader saves its checkpoint
after writing the corresponding output; a restart can repeat output. This is
not a checkpoint for a consumer's later effects. A caller that commits effects independently
uses its own `--after` checkpoint or `--snapshot`, regardless of another reader's
cursor. A baseline is provisional until `baseline_complete`; discard an
interrupted baseline and restart from the old committed cursor or a new snapshot.
Commit effects with their cursor. `caught_up` can advance a fully consumed empty
batch; filtered revision gaps are normal. The CLI rebuilds an expired cursor
from message pages and open-item entries/advisories before resuming.

Advisories retain their subtype payload; not every advisory has text. Use
`advisory-ack --item-id ID --advisory-id ID` for acknowledgment. Session end
changes availability without closing conversations. For focus and show, use
the existing grants; a show takes at most one device name or device ID. Do not
change grants or enrollment to make a command succeed.

Read the exact operation's success body: message writes return the message,
reply returns an entry, result returns both, and correlated revise/retract can
also return the acted entry. Use the installed Agent help for the remaining
file, focus, show and session commands.
