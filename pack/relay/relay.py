"""Move durable people messages between Tightbeam and Harklight Agent."""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

from addresses import Addresses
from agent_cli import AgentCLI
from harklight_agent import HarklightAgent
from outgoing import delivery_outcomes, prepare_send
from projection import event_for
from relay_state import RelayState
from tightbeam_people import TightbeamPeople


class Relay:
    def __init__(self, state: RelayState, addresses: Addresses, people: TightbeamPeople, agent):
        self.state = state
        self.addresses = addresses
        self.people = people
        self.agent = agent

    def prepare(self, record: dict) -> dict:
        kind = record["kind"]
        if kind == "send":
            return {"kind": kind, **prepare_send(record, self.addresses)}
        binding = self.state.binding(record["conversation_id"])
        if binding is None:
            return {"refusal": {"code": "conversation_undelivered",
                                "message": "The initial send did not open a conversation."}}
        request = {"kind": kind, **binding, "body": record["body"]}
        if kind == "update":
            current = self.agent.read_message(binding["item_id"])
            request["base_revision"] = record["revision"] - 1
            message = {**current["message"], "title": record["title"], "body": record["body"]}
            if record["answer_rule"]:
                actions = [
                    {"id": choice["id"], "label": choice["label"],
                     "kind": "value", "value": choice["id"]}
                    for choice in record["choices"]
                ]
                message["answer_ui"] = {
                    "schema": "attention-client.actions/1",
                    "actions": actions or [{"id": "reply", "label": "Reply", "kind": "text"}],
                }
            request["message"] = message
        if kind == "close" and request["body"]:
            request["closing_reply_id"] = str(uuid.uuid4())
        if kind == "reply" and record.get("address"):
            person = self.addresses.users.get(record["address"].removeprefix("user:"))
            if person is None:
                return {"refusal": {"code": "mention_unreachable",
                                    "message": "The mention has no Harklight person mapping."}}
            request["notify_person_id"] = person
        return request

    def deliver(self, row) -> dict:
        request = json.loads(row["request"])
        report = {"id": row["record_id"], "outcomes": []}
        if "refusal" in request:
            return {**report, "refusal": request["refusal"]}
        kind = request["kind"]
        if kind == "send" and request["selector"] == {"kind": "people", "people": []}:
            return {**report, "outcomes": request["missing"]}

        operation_id = row["operation_id"]
        if kind == "close" and request["body"]:
            reply = {**request, "kind": "reply"}
            response = self.agent.write(request["closing_reply_id"], reply)
            if "refusal" in response:
                return {**report, "refusal": response["refusal"]}

        response = self.agent.write(operation_id, request)
        if "refusal" in response:
            return {**report, "refusal": response["refusal"]}
        if kind == "send":
            report["outcomes"] = delivery_outcomes(request, response["recipients"])
            if request["selector"]["kind"] == "group":
                report["outcomes"] = [
                    {"address": f'group:{request["selector"]["group"]}',
                     "status": "reached" if response.get("item_id") else "not_reachable"}
                ]
            if response.get("item_id"):
                report.update(server_id=response["server_id"],
                              remote_conversation_id=response["item_id"])
        return report

    def report(self, result: dict) -> None:
        self.people.report(result)
        self.state.mark_reported(result["id"])

    def outbound(self) -> None:
        for result in self.state.unreported():
            self.report(result)
        for record in self.people.collect():
            row = self.state.prepare(record["id"], lambda: self.prepare(record))
            result = (
                self.deliver(row) if row["result"] is None else json.loads(row["result"])
            )
            if row["result"] is None:
                self.state.save_result(record["id"], result)
            self.report(result)

    def accept_pending(self) -> None:
        pending = self.state.pending_event()
        if pending is None:
            return
        event = pending["event"]
        self.people.event(event)
        if event["kind"] in {"chat", "answer"}:
            self.agent.receipt(pending["receipt_id"], event)
        self.state.complete_event(pending["checkpoint"])

    def inbound(self) -> None:
        self.accept_pending()
        for server_id, change, checkpoint in self.agent.changes(self.state.checkpoint()):
            event = event_for(server_id, change, self.addresses) if change is not None else None
            if event and self.state.owns(server_id, event["remote_conversation_id"]):
                self.state.prepare_event({
                    "event": event,
                    "checkpoint": checkpoint,
                    "receipt_id": str(uuid.uuid4()),
                })
                self.accept_pending()
            else:
                self.state.advance(checkpoint)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        addresses = Addresses(config["users"])
        connection = str(Path(config["connection"]).expanduser().resolve())
        sender = config["sender"]
        if not isinstance(sender, str) or not sender.strip():
            raise ValueError("sender must be a nonempty Harklight sender ID")

        args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (args.state_dir / "run.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            state = RelayState(args.state_dir / "relay.db", connection, sender)
            try:
                agent = HarklightAgent(AgentCLI(connection, args.state_dir / "agent"), sender, state)
                relay = Relay(state, addresses, TightbeamPeople(), agent)
                relay.outbound()
                relay.inbound()
            finally:
                state.close()
    except (KeyError, OSError, ValueError, RuntimeError, sqlite3.Error,
            subprocess.SubprocessError) as error:
        print(f"Harklight people relay: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
