---
name: harklight-agent
description: Send authorized Harklight notices, decisions, or questions from Tightbeam and handle replies or chat in the originating session. Use for Harklight communication, including from remote hosts.
---

<!-- HARKLIGHT_PACK_MANAGED -->

# Harklight for Tightbeam agents

> Follow the installed Tightbeam and Harklight help for exact options.

## Automatic lifecycle for your own messages

From your authenticated Tightbeam session, send through
`tightbeam harklight-send`, retain the plain message ID, and end the turn.
When the send commits, it automatically subscribes the originating session;
a reply or chat on its message wakes the same session with the actual entry.
This Tightbeam send route needs no polling or manual wake.
Tightbeam owns listening. Do not start an agent-owned `listen --next` or
`listen --follow`, or substitute another agent for the origin.

The distinct message-management operations also manage wakes automatically:

- A committed retraction withdraws one message and cancels its future wakes.
- A committed revision updates one message in place and keeps its subscription
  under the same message ID.
- A committed superseding send opens one subscription for its new message and
  cancels future wakes on the sending session's successfully superseded old
  messages. Warnings and other sessions' subscriptions are handled below.

The contract ends every subscription when the conversation completes; a
terminal answer alone does not establish conversation completion or listener
cleanup. The existing proof does not expose per-message unsubscribe. Only a
confirmed commit changes wakes, at most once. A minted message ID is returned
even for an uncertain or refused send; it does not by itself establish that the message
was sent or subscribed. A failure before an ID was minted explains why no send
happened. Never fabricate an ID.

Revision and supersession are different operations. Do not alias supersede to
revise or emulate missing Harklight behavior locally. If the required server
or CLI operation is unavailable, report the gap to the Harklight owner.

Tightbeam owns this subscription and wake integration. Standalone Agent 0.1.5
rejects its native Codex listen route; its one-shot `read` can retrieve entries
without a listener, followed by inspect, ACK and reply/result. That is separate
from Tightbeam delivery. Neither a standalone support declaration nor a queued
wake establishes same-session delivery. Do not add a raw waiter or read loop
to a Tightbeam subscription.

Choose the message form that fits the user's task. Informational updates use
an explicit **Seen** acknowledgment. Decisions use structured choices with
meaningful labels and stable values, plus a text reply when useful. Open
questions use a text reply. Do not put numbered choices only in the body and
require the person to type an option. Opening a message never counts as Seen
or as a response. Include the product in the title when using the shared sender.

## Configuration and sending

Use the existing enrolled identity and its granted sender ID through the
configuration route established for the command's actual execution context.
Do not infer the gateway's configuration from an agent shell, or assume raw
post-wake commands share the gateway's identity, CA, origin port or journal.

Origin, dashboard and relay ports are distinct; never guess one from another.
If a command cannot run, preserve its actual error and execution context for
the existing service owner. Do not infer a configuration deficiency, create
another identity, copy private keys, or change the live service environment to
make it work. Keep the existing journal for recovery.

Send from your authenticated local Tightbeam session:

```sh
tightbeam harklight-send --session new --sender-id "$HARKLIGHT_SENDER" \
  --title "Product: choose the next step" \
  --body "Select an option or write a note." \
  --choices-json '["Proceed", "Defer"]'
```

`HARKLIGHT_SENDER` here is the sender ID already granted to the enrollment.
The choice array contains strings; each exact label is its returned value.
Omit `--choices-json` for an open text question. Keep the printed plain
`messageId` for later Tightbeam commands. `--message` takes that ID;
Tightbeam uses its recorded Harklight handle and sender, so you do not supply
them again. Keep the result's `opId` when present for an uncertain outcome's
record. A Harklight handle, when reported, identifies the conversation and is
not a Tightbeam session key.

Tightbeam supplies the controller route. Do not add raw CLI `--route` or
`--controller` flags to `tightbeam harklight-send`. Its `--files-json` takes
an array of file paths. Files use the server's published limits and verified
transfer; preserve a failed draft with all attachments rather than silently
dropping files. Use the installed command's `--help` for supported inputs.

The current Tightbeam send command has no informational/Seen flag. Use the
existing notice helper below when that is the required message form; do not
invent a flag or represent a text reply as Seen.

## Revise, retract or supersede

Proactively keep conversations current as work changes, so the person is
not left answering stale questions. Useful ways to do this include revising
the same open request when only its details need correction, superseding it
when a new request replaces it, and retracting an outstanding request that is
obsolete, canceled or no longer needs an answer. Use judgment about when an
update helps and stay within the task's existing authority; these examples
are not an exhaustive checklist or a requirement to mutate every message.

Preserve useful history and already received answers. Retraction withdraws a
request; it does not undo an action already taken. Do not use a replacement to
bypass a terminal refusal. Read the actual operation result and follow this
skill's operation-specific uncertainty handling, including supported
same-operation recovery for unresolved sends, before claiming that a request
was updated, withdrawn or replaced. An uncertain outcome is not confirmed cleanup.

In these examples, `HARKLIGHT_MESSAGE_ID` is the plain ID returned by the send.
To revise that message in place, supply its current base revision and title:

```sh
tightbeam harklight-revise --message "$HARKLIGHT_MESSAGE_ID" \
  --base-revision 1 --title "Product: updated request" \
  --body "The revised details."
```

Use the actual base revision. The command also accepts `--choices-json` and
`--clear-choices`. A committed revise reports the new `revision` and
`wakeEffect: "kept"`. A stale base revision is refused with Harklight's reason
and current revision; the subscription stays unchanged.

To withdraw one message:

```sh
tightbeam harklight-retract --message "$HARKLIGHT_MESSAGE_ID"
```

A committed retract reports `wakeEffect: "ended"`. It stops wakes for entries
captured after the commit, leaving other messages on the same handle alone.

To replace one or more messages with a new message, repeat `--supersedes` once
per replaced ID on a new send:

```sh
tightbeam harklight-send --session new --sender-id "$HARKLIGHT_SENDER" \
  --title "Product: replacement request" --body "Use these updated details." \
  --supersedes "$HARKLIGHT_OLD_ID_1" --supersedes "$HARKLIGHT_OLD_ID_2"
```

Keep the new message ID. Read the result's `supersedes` list: each distinct
listed ID appears once, in the given order. A Harklight warning such as
`invalid`, `unknown` or `closed` leaves that target's subscription unchanged
and is reported verbatim; it need not prevent the new send from committing.
The per-target effect is `unchanged` for such a warning or `ended` for the
sender's superseded message whose future wakes are canceled.
Successfully superseded messages of the sending session cancel future wakes
at commit. Tightbeam acknowledges their self-caused closing terminals without
waking the agent; their subscriptions end when that acknowledgment is recorded.
`acknowledgment: "pending"` means wakes are canceled but acknowledgment is
pending. `acknowledged` means that acknowledgment was recorded.
`not_needed` means the conversation completed before the terminal was captured: the
subscription ended without an acknowledgment attempt, then or after restart.
The result reports the state recorded when it returns, not a later state.
`failed` includes the reason and reports the old subscription still
open, with no wake for that terminal and no automatic acknowledgment retry.
The agent may acknowledge that exact entry with raw `harklight-agent`.
Pending acknowledgments survive restart and finish once without a duplicate;
conversation completion ends the subscription if no terminal needs acknowledgment.

Eligible revise, retract, settle and supersede actions are not refused merely
because another session sent the message. Harklight's existing authority
decides whether they apply; the original sender remains the wake recipient.
For a superseded target held by another session, `other_session` leaves its
subscription under the existing delivery rules so that session receives the
Harklight `superseded` terminal once and acknowledges it. Tightbeam does not
synthesize a terminal Harklight did not emit. `no_subscription` means the
superseded target has no Tightbeam send record. Revise or retract instead uses
the target's recorded handle and sender; a committed change affects that
subscription. A cross-session retract does not promise a notice to its sender.

If `--message` names no Tightbeam send record, the command refuses without a
Harklight operation and explains that Tightbeam does not know the message's
Harklight session. Raw `harklight-agent` is the route for a message unknown to
Tightbeam; consult its installed `--help`. Raw revise/retract bypass
Tightbeam's automatic wake effects;
use the Tightbeam commands for the lifecycle described here.

## Read results and settle an uncertain send

Read `outcome` and `wakeEffect`, not just the message ID. `committed` confirms
the operation; `refused` means it was not applied; `outcome_unknown` means it
may or may not have applied; `failed` means the operation did not reach
Harklight. Non-committed outcomes exit nonzero and still report their fields
and a plain reason. `command` identifies `send`, `revise`, `retract` or
`settle`. Wake effects are `subscribed`, `kept`, `ended` or `none`.
Results include `messageId` when minted, `senderId` and `handle` when known,
`opId` when assigned, and the new `revision` for a committed revise.

An `outcome_unknown` send is pending and unregistered: no subscription is open
yet, and its ID is information only until the send is settled. Revise, retract
or a superseding send naming that unresolved ID is refused as a whole, with no
Harklight operation or wake effect. Settle that send explicitly:

```sh
tightbeam harklight-settle --message "$HARKLIGHT_MESSAGE_ID"
```

This runs the existing same-operation recovery once, using the recorded op ID
and unchanged inputs. It creates no new send or prepare. If it confirms commit,
the original sender's subscription and any supersede effects are applied once.
If it establishes refusal, the result says the message was not sent. If still
unresolved, it says so, reports `wakeEffect: "none"`, and lifecycle actions on
the ID remain refused. You may explicitly settle it again; do not put settle
in a timer, poll or retry loop. You can also leave it for existing recovery at
the next gateway start. Tightbeam does not otherwise retry it automatically.
An already-settled or unknown ID is refused without a Harklight operation,
with its settled outcome or the missing-record explanation. After settlement,
ordinary lifecycle commands apply according to the established message state.

An uncertain revise or retract leaves the subscription as it was and applies
no wake effect. The change may or may not have reached Harklight. Tightbeam
does not recover or automatically retry that operation, including at restart;
the agent may explicitly issue the same command again as a new operation with
its own result. A later committed retract or supersede, or conversation
completion, ends the subscription. `harklight-settle` is for unresolved sends,
not for recovering revise or retract outcomes.

A committed retract or supersede reports `pendingDelivery` entries by message
ID and entry identity, captured before its commit and not yet delivered. Each
still arrives once, including
across restart, marked as received before retraction or before supersession
by the named replacement ID. The marker accompanies the entry even if its
wake was already queued or sealed for delivery. Tightbeam does not acknowledge human replies or chat
for the agent. Handle the delivered entry below; do not mistake its later
arrival for a new post-commit reply or repeat its effect. Entries captured
after the ending commit do not wake the session.

## Read one of your own sent messages

Agent 0.1.9 or newer can read one of this origin's messages from a compatible
Server by its sender and message IDs:

```sh
harklight-agent message-get --sender-id S --message-id M
harklight-agent message-get --sender-id S --message-id M --revision N
```

Use the `senderId` and `messageId` from the send result. Omit `--revision` to
read the latest version; use it to select a retained revision. This read does
not mark the message Seen, acknowledge an event or update the local journal.
`revision_unavailable` means the requested revision is no longer retained; it
is gone. It does not retrieve replies; those arrive through the wake below.

## Handle a delivered entry

Read the wake's entry and handling instructions. Correlate the exact handle,
sender/message identity, request revision and event ID. Use `entry.kind` and
`entry.author` to distinguish discussion from terminal answers. The variables
below stand for the values in that entry; `HARKLIGHT_REQUEST` is its request's
message ID. Run the current raw commands from the originating session using
the configuration route confirmed for that execution context. Report an actual
command failure to its owner instead of assuming a route, copying credentials
or creating a replacement.

```sh
harklight-agent ack --session "$HARKLIGHT_SESSION" --event "$HARKLIGHT_EVENT"
```

Explicitly acknowledge before acting. Printing the entry is not an
acknowledgment. Check prior effects before repeating an action on a redelivery;
an acknowledgment alone does not establish that the action happened.

For a person discussion, reply to the exact request and event:

```sh
harklight-agent reply --session "$HARKLIGHT_SESSION" \
  --request "$HARKLIGHT_REQUEST" --in-reply-to "$HARKLIGHT_EVENT" \
  --body "The request is complete."
```

Use a body that states the actual outcome. A conversation reply is not a
terminal answer or a grant of new authority. Receiving discussion after a
terminal does not prove that replying is still allowed: the recorded later
discussion was delivered and acknowledged, but reply was refused because the
request was closed. Preserve that refusal; do not reopen or send a replacement
merely to answer it. For an `answered`
terminal, reconcile earlier effects before applying its authorized outcome
at most once, then report its disposition:

```sh
harklight-agent result --session "$HARKLIGHT_SESSION" \
  --request "$HARKLIGHT_REQUEST" --in-reply-to "$HARKLIGHT_EVENT" \
  --status applied
```

Use `applied` only when the effect is established, `refused` when it cannot be
applied, or `received` when the outcome remains uncertain. If an earlier
attempt may have taken effect, check it before acting again. Keep the original
event, request and revision identities. Cleared, expired or superseded
terminals stop work on that request and are not approval. Retraction ends the request; do not
answer it, report a result or reopen it implicitly.

For received files, inspect each local path and transfer outcome. Transfer
does not prove this session read the file. After acknowledgment, report
`harklight-agent file-use` with the exact session, event and file and either
`--used` or `--unusable --reason`. Do not claim use for `not_transferred` files.

## Raw command recovery and references

Preserve the original operation UUID and journal. An uncertain operation is
not a refusal; do not send another message to discover whether it committed.
Use `tightbeam harklight-settle` for an unresolved Tightbeam send; a raw CLI
retry receipt does not establish Tightbeam's binding or wake effects. Keep
the current raw `harklight-agent ack/reply/result` handling after a wake;
there is no Tightbeam reply verb.

For a raw acknowledgment/reply/result operation that reports an uncertain
outcome and an operation ID, recover that same operation
with `harklight-agent retry --op-id "$HARKLIGHT_OP_ID"`. Do not apply an action
bound to an older request revision. This raw recovery instruction does not
apply to Tightbeam lifecycle commands and does not authorize automatic retries
or a retry loop.

For raw commands outside Tightbeam, consult the installed Harklight Agent skill and its help. This skill covers Tightbeam-managed subscriptions and wakes.
