> Protocol 0.2 source targets are documented in the repository README. Use this
> guidance with a confirmed compatible Tightbeam, Agent and Server installation
> after paired acceptance. Source verification does not update an installation.

## Decisions the operator must handle in person

Some decision requests addressed to the operator need them in person: they have to log in,
handle a device or do something physical. Product owners and delivery owners
can't answer those. When you see one, turn it into a Harklight request to the operator
with the harklight-agent skill and send through `tightbeam harklight-send`.
Keep `messageId` when issued and retain `opId` to settle an uncertain send
that has no item ID yet. A committed send automatically subscribes
your message; end your turn and let Tightbeam wake this same originating
session on their reply or chat. This Tightbeam send route needs no polling or
manual wake. Use the protocol 0.2 harklight-agent skill for the delivered
change: chat replies use its actual entry ID, while answer results use the item
ID. Tightbeam records handoff after dispatch; report actual file use separately. When they answer, rule the decision request
according to what they said.

## Reporting to the operator on Harklight

Send to the operator through Tightbeam. Answer them with `harklight-agent`.

- **Sending.** Start a new message with `tightbeam harklight-send`. To change
  or withdraw a message you sent, use `harklight-revise` or `harklight-retract`.
  Use `harklight-settle` to recover a saved unresolved operation with its
  original identifiers. A committed registered send wakes you when they answer,
  so don't poll.
- **Answering.** When Tightbeam delivers one of the operator's Harklight replies or
  chats to you, answer it in the same thread. Use Agent 0.2 `reply` for a chat
  or `result` for an answered choice, as the delivered change and the
  harklight-agent skill describe. Always answer their chats. Read whatever
  entries you need in order to answer.
- **Conversation state.** Chats can continue after an answer or retraction.
  Preserve an actual refusal and its reason; do not replace the request merely
  because a chat follows a terminal.

Use Seen for informational messages through the supported installed interface.
Put your product's name in the title, because the sender is shared. This guidance
targets protocol 0.2 with matching Server, Agent, app, web and Tightbeam integration.

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
