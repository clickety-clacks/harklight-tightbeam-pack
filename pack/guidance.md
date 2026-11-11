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

Send to the operator through Tightbeam. Answer them with `harklight-agent`.

- **Sending.** Start a new message with `tightbeam harklight-send`. To change
  or withdraw a message you sent, use `harklight-revise`, `harklight-retract`
  or `harklight-settle`. A send wakes you when they answer, so don't poll.
- **Answering.** When Tightbeam delivers one of the operator's Harklight replies or
  chats to you, answer it in the same thread. Use `harklight-agent ack`, then
  `reply` (or `result` for an answered choice), as the delivered message and
  the harklight-agent skill describe. Always answer their chats. Read whatever
  entries you need in order to answer.
- **If a reply is refused** because you already answered that chat message,
  send a new message with `tightbeam harklight-send`.

Send has no Seen-only form yet, so send notices as ordinary messages. Put your
product's name in the title, because the sender is shared. When Tightbeam ships
its own reply and chat commands, use them instead of `harklight-agent`.

Product owners and delivery owners reach the operator this way.

- Delivery owners: show your product's progress by updating its Harklight
  progress bar. Don't send milestone reports. If you can't create or update a
  progress bar yet, that's fine; you don't have access to it yet, so send
  nothing instead. The first time you find you can create or update one, send
  the operator one Harklight message saying so, so they can finalize this guidance.
- Product owners send product-level milestones only: a job or component of
  your product that started or finished (for example "component X of product Y
  finished"), or something waiting on the operator, such as a product decision, a scope
  or priority question, or a risk they would want to know about. Leave out
  working steps such as opening a terminal, cards, assignments, attests,
  commits and sessions.
