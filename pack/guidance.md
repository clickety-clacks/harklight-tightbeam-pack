## Decisions the operator must handle in person

Some decision requests addressed to the operator need them in person: they have to log in,
handle a device or do something physical. Product owners and delivery owners
can't answer those. When you see one, turn it into a Harklight request to the operator
with the harklight-agent skill and send through `tightbeam harklight-send`.
Keep the printed plain message ID. A committed send automatically subscribes
your message; end your turn and let Tightbeam wake this same originating
session on their reply or chat. This Tightbeam send route needs no polling or
manual wake; the skill separately describes its compatibility fallback.
Handle the delivered entry with the skill's raw `harklight-agent`
ack/reply/result commands. When they answer, rule the decision request
according to what they said.

## Reporting to the operator on Harklight

Harklight is the channel for reporting to the operator and asking them questions. Keep
what you send, blockers included, at the level of the ask or the product, not
what happens under the hood. Include an implementation detail only when it
matters to what the product is or does.

Take questions and issues first to the agent that acts as the operator's proxy or
executive. Go to the operator yourself only when no such agent exists or it does not
respond.

Send to the operator through Tightbeam. Answer them with `harklight-agent`.

- **Sending.** Start a new message with `tightbeam harklight-send`. To change
  or withdraw a message you sent, use `harklight-revise`, `harklight-retract`
  or `harklight-settle`. A send wakes you when they answer, so don't poll.
- **Answering.** When Tightbeam delivers one of the operator's Harklight replies or
  chats to you, answer it in the same thread. Use `harklight-agent ack`, then
  `reply` (or `result` for an answered choice), as the delivered message and
  the harklight-agent skill describe. Always answer their chats. Read whatever
  entries you need in order to answer.
- **If a reply is refused** (an older Server may still close a chat after an
  answer), send a new message with `tightbeam harklight-send`. A late chat
  still gets an answer.

Send has no Seen-only form yet, so send notices as ordinary messages. Put your
product's name in the title, because the sender is shared. When Tightbeam ships
its own reply and chat commands, use them instead of `harklight-agent`.
