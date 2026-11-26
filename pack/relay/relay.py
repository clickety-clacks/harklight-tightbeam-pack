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
            request["base_revision"] = current["revision"]
            message = {**current["message"], "title": record["title"], "body": record["body"]}
            if record["answer_rule"] and record["choices"] is not None:
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
            return {**report, "outcomes": request["missing"],
                    "refusal": {"code": "no_recipients", "message": "No recipients are mapped."}}

        operation_id = row["operation_id"]
        if kind == "close" and request["body"]:
            reply = {**request, "kind": "reply"}
            response = self.agent.write(request["closing_reply_id"], reply)
            if "refusal" in response:
                return {**report, "refusal": response["refusal"]}

        response = self.agent.write(operation_id, request)
        if "refusal" in response:
            report["refusal"] = response["refusal"]
        if "remote_revision" in response:
            report["remote_revision"] = response["remote_revision"]
        if kind == "send" and "recipients" in response:
            delivered = "item_id" in response
            report["outcomes"] = delivery_outcomes(request, response["recipients"], delivered)
            if delivered:
                report.update(server_id=response["server_id"],
                              remote_conversation_id=response["item_id"])
        return report

    def report(self, result: dict) -> None:
        self.people.report(result)
        self.state.mark_reported(result["id"])

    def deliver_record(self, record: dict) -> None:
        if record.get("remote_conversation_id"):
            self.state.remember_binding(record)
        row = self.state.prepare(record["id"], lambda: self.prepare(record))
        if row["result"] is None:
            result = self.deliver(row)
            self.state.save_result(record["id"], result)
        else:
            result = json.loads(row["result"])
        self.report(result)

    def outbound(self) -> None:
        attempted = set()
        errors = []
        for result in self.state.unreported():
            attempted.add(result["id"])
            try:
                self.report(result)
            except (KeyError, TypeError, OSError, ValueError, RuntimeError,
                    subprocess.SubprocessError) as error:
                errors.append(error)
        for record in self.people.collect():
            if record["id"] not in attempted:
                try:
                    self.deliver_record(record)
                except (KeyError, TypeError, OSError, ValueError, RuntimeError,
                        subprocess.SubprocessError) as error:
                    errors.append(error)
        if errors:
            raise errors[0]

    def accept_pending(self) -> None:
        pending = self.state.pending_event()
        if pending is None:
            return
        event = pending["event"]
        self.people.event(event)
        receipt = pending if pending["receipt_id"] is not None else None
        self.state.complete_event(pending["checkpoint"], receipt)

    def receipts(self) -> None:
        failed = False
        for receipt in self.state.receipts():
            try:
                self.agent.receipt(receipt["operation_id"], json.loads(receipt["event"]))
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                failed = True
                continue
            self.state.complete_receipt(receipt["event_key"])
        if failed:
            raise RuntimeError("One or more Harklight receipts are pending retry")

    def inbound(self) -> None:
        self.accept_pending()
        held = set()
        for server_id, change, checkpoint in self.agent.changes(self.state.checkpoint()):
            item_id = change.get("data", {}).get("item_id") if change is not None else None
            if item_id is not None and (
                item_id in held or self.state.binding_unreported(server_id, item_id)
            ):
                held.add(item_id)
                continue
            try:
                event = event_for(server_id, change, self.addresses) if change is not None else None
            except (KeyError, TypeError, ValueError):
                if item_id is None:
                    raise
                held.add(item_id)
                continue
            if event:
                try:
                    binding = self.people.lookup(server_id, item_id)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    held.add(item_id)
                    continue
                if binding is None and (
                    self.state.owns(server_id, item_id) or self.state.has_unresolved_send()
                ):
                    held.add(item_id)
                    continue
                if binding is not None and not any(
                    revision["remote_revision"] == event["remote_revision"]
                    for revision in binding["revisions"]
                ):
                    held.add(item_id)
                    continue
            if held:
                checkpoint = self.state.checkpoint()
            if event and binding is not None:
                self.state.prepare_event({
                    "event": event,
                    "checkpoint": checkpoint,
                    "receipt_id": (
                        str(uuid.uuid4()) if event["kind"] in {"chat", "answer"}
                        and change.get("pending") is not False else None
                    ),
                })
                self.accept_pending()
            else:
                self.state.advance(checkpoint)
        if held:
            raise RuntimeError("One or more Harklight events are waiting for a valid payload or send report")


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
                failures = []
                for action in (relay.outbound, relay.inbound, relay.receipts):
                    try:
                        action()
                    except (KeyError, TypeError, OSError, ValueError, RuntimeError,
                            sqlite3.Error, subprocess.SubprocessError):
                        failures.append(action.__name__)
                if failures:
                    raise RuntimeError(f"Retry required for {', '.join(failures)}")
            finally:
                state.close()
    except (KeyError, OSError, ValueError, RuntimeError, sqlite3.Error,
            subprocess.SubprocessError) as error:
        print(f"Harklight people relay: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
