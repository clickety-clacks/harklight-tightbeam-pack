import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pack" / "relay"))

from addresses import Addresses
from relay import Relay
from relay_state import RelayState
from tightbeam_people import TightbeamRefusal


SEND = {
    "id": "conversation",
    "conversation_id": "conversation",
    "kind": "send",
    "addresses": ["user:reader", "user:unmapped"],
    "title": "Launch",
    "body": "Choose the launch date.",
    "choices": [{"id": "thu", "label": "Thursday"}],
    "answer_rule": {"kind": "named", "address": "user:reader"},
}
ANSWER = {
    "kind": "answer",
    "rev": 20,
    "data": {
        "item_id": "shared-item",
        "answer_id": "answer-1",
        "request_revision": 1,
        "terminal": {
            "answer": "thu",
            "speaker": {"kind": "person", "id": "person-1", "display_name": "Reader"},
        },
    },
}


class AgentFixture:
    def __init__(self):
        self.calls = []
        self.receipts = []
        self.failure = None

    def write(self, operation_id, request):
        self.calls.append((operation_id, request))
        if self.failure:
            raise self.failure
        return {
            "server_id": "service",
            "item_id": "shared-item",
            "remote_revision": 1,
            "recipients": [{"person_id": "person-1", "status": "reached"}],
        }

    def changes(self, checkpoint):
        if checkpoint != {"rev": 20}:
            yield "service", ANSWER, {"rev": 20}

    def receipt(self, operation_id, event):
        self.receipts.append((operation_id, event["event_id"]))


class PeopleFixture:
    def __init__(self):
        self.records = [SEND]
        self.reports = []
        self.events = []
        self.lose_report_response = False
        self.lose_event_response = False

    def collect(self):
        return self.records[:]

    def report(self, result):
        self.reports.append(result)
        self.records.clear()
        if self.lose_report_response:
            raise RuntimeError("no report response")

    def lookup(self, server_id, item_id):
        return {"conversation_id": "conversation",
                "revisions": [{"remote_revision": 1, "revision": 4}]}

    def event(self, event):
        self.events.append(event)
        if self.lose_event_response:
            raise RuntimeError("no event response")


class RelayTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "relay.db"
        self.agent = AgentFixture()
        self.people = PeopleFixture()

    def relay(self, users):
        state = RelayState(self.path, "connection", "sender")
        self.addCleanup(state.close)
        return Relay(state, Addresses(users), self.people, self.agent)

    def test_unknown_send_reuses_operation_and_mapping(self):
        relay = self.relay({"reader": "person-1"})
        self.agent.failure = RuntimeError("no send response")
        with self.assertRaisesRegex(RuntimeError, "no send response"):
            relay.outbound()
        self.agent.failure = None
        self.relay({"reader": "person-2"}).outbound()
        self.assertEqual(self.agent.calls[0], self.agent.calls[1])
        self.assertEqual(self.agent.calls[0][1]["answer_policy"],
                         {"kind": "named", "people": ["person-1"]})
        self.assertCountEqual(
            self.people.reports[0]["outcomes"],
            [
                {"address": "user:reader", "status": "reached"},
                {"address": "user:unmapped", "status": "not_reachable",
                 "reason": "no_person_mapping"},
            ],
        )

    def test_lost_report_and_event_acknowledgments_replay_original_data(self):
        relay = self.relay({"reader": "person-1"})
        self.people.lose_report_response = True
        with self.assertRaisesRegex(RuntimeError, "no report response"):
            relay.outbound()
        self.people.lose_report_response = False
        relay.outbound()
        self.assertEqual(len(self.agent.calls), 1)
        self.assertEqual(self.people.reports[0], self.people.reports[1])

        self.people.lose_event_response = True
        with self.assertRaisesRegex(RuntimeError, "no event response"):
            relay.inbound()
        self.assertIsNone(relay.state.checkpoint())
        self.assertEqual(self.agent.receipts, [])
        self.people.lose_event_response = False
        restarted = self.relay({"replacement": "person-1"})
        restarted.inbound()
        restarted.receipts()
        self.assertEqual(self.people.events[0], self.people.events[1])
        self.assertEqual(self.people.events[1]["speaker"]["address"], "user:reader")
        self.assertEqual(restarted.state.checkpoint(), {"rev": 20})
        self.assertEqual(len(self.agent.receipts), 1)

    def test_atomic_refusal_has_no_address_outcomes_or_remote_binding(self):
        relay = self.relay({"reader": "person-1"})
        refusal = {"code": "recipient_refused", "message": "Recipient outside organization"}
        self.agent.write = lambda *_: {"refusal": refusal}
        relay.outbound()
        self.assertEqual(self.people.reports, [
            {"id": "conversation", "outcomes": [], "refusal": refusal}
        ])
        self.assertIsNone(relay.state.binding("conversation"))

    def test_decider_unreachable_reports_atomic_failure_and_candidate_outcomes(self):
        relay = self.relay({"reader": "person-1", "unmapped": "person-2"})
        self.agent.write = lambda *_: {
            "refusal": {"code": "decider_unreachable", "message": "Decider unreachable"},
            "recipients": [
                {"person_id": "person-1", "status": "unreachable"},
                {"person_id": "person-2", "status": "reached"},
            ],
        }
        relay.outbound()
        result = self.people.reports[0]
        self.assertEqual(result["refusal"]["code"], "decider_unreachable")
        self.assertCountEqual(result["outcomes"], [
            {"address": "user:reader", "status": "not_reachable"},
            {"address": "user:unmapped", "status": "refused", "reason": "not_delivered"},
        ])
        self.assertIsNone(relay.state.binding("conversation"))

    def test_group_and_user_together_refuses_the_whole_send(self):
        relay = self.relay({"reader": "person-1"})
        self.people.records = [{**SEND, "addresses": ["user:reader", "group:example"]}]
        relay.outbound()
        self.assertEqual(self.people.reports[0]["refusal"]["code"], "unsupported")
        self.assertEqual(self.people.reports[0]["outcomes"], [])
        self.assertEqual(self.agent.calls, [])

    def test_refused_or_unavailable_receipt_does_not_hold_the_feed(self):
        relay = self.relay({"reader": "person-1"})
        relay.outbound()
        relay.inbound()
        self.assertEqual(relay.state.checkpoint(), {"rev": 20})
        original = relay.state.receipts()[0]["operation_id"]

        def unavailable(*_):
            raise RuntimeError("connection lost")

        self.agent.receipt = unavailable
        with self.assertRaisesRegex(RuntimeError, "pending retry"):
            relay.receipts()
        self.assertEqual(relay.state.receipts()[0]["operation_id"], original)

    def test_unreported_send_holds_its_inbound_checkpoint(self):
        relay = self.relay({"reader": "person-1"})
        self.people.lose_report_response = True
        with self.assertRaisesRegex(RuntimeError, "no report response"):
            relay.outbound()
        with self.assertRaisesRegex(RuntimeError, "waiting"):
            relay.inbound()
        self.assertEqual(self.people.events, [])
        self.assertIsNone(relay.state.checkpoint())

    def test_update_uses_service_revision_and_preserves_omitted_choices(self):
        relay = self.relay({"reader": "person-1"})
        relay.outbound()
        ui = {"schema": "attention-client.actions/1", "actions": [{"kind": "text"}]}
        self.agent.read_message = lambda _: {"revision": 3, "message": {"answer_ui": ui}}
        request = relay.prepare({
            **SEND, "kind": "update", "revision": 7, "choices": None,
            "title": "New title",
        })
        self.assertEqual(request["base_revision"], 3)
        self.assertEqual(request["message"]["answer_ui"], ui)
        self.assertEqual(request["message"]["title"], "New title")

    def test_remote_lookup_recovers_binding_without_local_outgoing_state(self):
        relay = self.relay({"reader": "person-1"})
        self.assertFalse(relay.state.owns("service", "shared-item"))
        relay.inbound()
        self.assertEqual(self.people.events[0]["remote_revision"], 1)
        self.assertNotIn("revision", self.people.events[0])
        self.assertEqual(relay.state.checkpoint(), {"rev": 20})

    def test_unbound_remote_revision_holds_event_until_update_is_reported(self):
        relay = self.relay({"reader": "person-1"})
        relay.outbound()
        lookup = self.people.lookup
        self.people.lookup = lambda *_: {"conversation_id": "conversation", "revisions": []}
        with self.assertRaisesRegex(RuntimeError, "waiting"):
            relay.inbound()
        self.assertEqual(self.people.events, [])
        self.assertIsNone(relay.state.checkpoint())

        self.people.lookup = lookup
        relay.inbound()
        self.assertEqual(self.people.events[0]["remote_revision"], 1)
        self.assertEqual(relay.state.checkpoint(), {"rev": 20})

    def test_unresolved_send_holds_events_for_yet_unbound_conversation(self):
        relay = self.relay({"reader": "person-1"})
        self.agent.failure = RuntimeError("no send response")
        with self.assertRaisesRegex(RuntimeError, "no send response"):
            relay.outbound()
        self.people.lookup = lambda *_: None
        with self.assertRaisesRegex(RuntimeError, "waiting"):
            relay.inbound()
        self.assertEqual(self.people.events, [])
        self.assertIsNone(relay.state.checkpoint())

    def test_refused_revision_gap_retains_event_and_allows_following_chat_once(self):
        relay = self.relay({"reader": "person-1"})
        relay.outbound()
        skipped = {**ANSWER, "data": {**ANSWER["data"], "request_revision": 2}}
        chat = {"kind": "entry", "data": {
            "item_id": "shared-item", "shared_entry_id": "chat-3", "author": "person",
            "request_revision": 3, "text": "Deliver",
            "speaker": {"kind": "person", "id": "person-1", "display_name": "Reader"},
        }}
        self.people.lookup = lambda *_: {"revisions": [{"remote_revision": 1}, {"remote_revision": 3}]}

        accepted = self.people.event
        attempted = []

        def refuse_gap(event):
            attempted.append(event["event_id"])
            if event["remote_revision"] == 2:
                raise TightbeamRefusal("people-event", 404, {
                    "code": "revision_unbound", "message": "No accepted report",
                })
            if not any(old["event_id"] == event["event_id"] for old in self.people.events):
                accepted(event)

        self.people.event = refuse_gap
        self.agent.changes = lambda _: (
            ("service", row, {"rev": rev}) for row, rev in [(skipped, 20), (chat, 21)]
        )
        relay.inbound()
        self.assertEqual(relay.state.checkpoint(), {"rev": 21})
        restarted = self.relay({"new-reader": "person-1"})
        restarted.inbound()
        row = restarted.state.db.execute("SELECT * FROM refused_events").fetchone()
        self.assertEqual(row["later_bound_revision"], 3)
        self.assertEqual(json.loads(row["event"])["speaker"]["address"], "user:reader")
        self.assertEqual(json.loads(row["error"])["code"], "revision_unbound")
        self.assertEqual(len(restarted.state.receipts()), 1)
        self.assertEqual(len(self.people.events), 1)
        self.assertEqual(attempted.count("answer-1"), 1)

    def test_pending_unbound_event_is_held_when_a_later_report_could_bind_it(self):
        relay = self.relay({"reader": "person-1"})
        relay.state.advance({"rev": 19})
        pending = {
            "event": {"server_id": "service", "remote_conversation_id": "shared-item",
                      "kind": "answer", "event_id": "future", "remote_revision": 2},
            "checkpoint": {"rev": 20}, "receipt_id": None,
        }
        relay.state.prepare_event(pending)

        def refuse(_):
            raise TightbeamRefusal("people-event", 404, {"code": "revision_unbound"})

        self.people.event = refuse
        with self.assertRaises(TightbeamRefusal):
            relay.inbound()
        self.assertEqual(relay.state.pending_event(), pending)
        self.assertEqual(relay.state.checkpoint(), {"rev": 19})
        self.assertIsNone(relay.state.db.execute("SELECT 1 FROM refused_events").fetchone())

    def test_group_send_reports_one_address_and_binds_one_conversation(self):
        relay = self.relay({"reader": "person-1"})
        self.people.records = [{**SEND, "addresses": ["group-id:opaque-group"]}]
        self.agent.write = lambda operation_id, request: self.group_receipt(operation_id, request)
        relay.outbound()
        [(operation_id, request)] = self.agent.calls
        self.assertTrue(operation_id)
        self.assertEqual(request["selector"], {"kind": "group", "group_id": "opaque-group"})
        self.assertEqual(request["answer_policy"], {"kind": "named", "people": ["person-1"]})
        self.assertEqual(self.people.reports, [{
            "id": "conversation", "outcomes": [
                {"address": "group-id:opaque-group", "status": "reached"},
            ],
            "server_id": "service", "remote_conversation_id": "shared-item", "remote_revision": 1,
        }])

    def group_receipt(self, operation_id, request):
        self.agent.calls.append((operation_id, request))
        return {
            "server_id": "service", "item_id": "shared-item", "remote_revision": 1,
            "recipients": {"kind": "group", "group_id": "opaque-group"},
        }

    def test_group_name_and_first_answer_policy_are_frozen_during_retry(self):
        relay = self.relay({"reader": "person-1"})
        self.people.records = [{
            **SEND, "addresses": ["group:Release Team"], "answer_rule": {"kind": "first"}
        }]
        self.agent.failure = RuntimeError("no send response")
        with self.assertRaisesRegex(RuntimeError, "no send response"):
            relay.outbound()
        self.agent.write = self.group_receipt
        self.relay({"reader": "different-person"}).outbound()
        self.assertEqual(self.agent.calls[0], self.agent.calls[1])
        request = self.agent.calls[1][1]
        self.assertEqual(request["selector"], {"kind": "group", "name": "Release Team"})
        self.assertEqual(request["answer_policy"], {"kind": "first"})
        self.assertEqual(self.people.reports[0]["outcomes"], [
            {"address": "group:Release Team", "status": "reached"},
        ])

    def test_group_decider_refusal_does_not_invent_member_outcomes(self):
        relay = self.relay({"reader": "person-1"})
        self.people.records = [{**SEND, "addresses": ["group:Release Team"]}]
        self.agent.write = lambda *_: {
            "refusal": {"code": "decider_unreachable", "message": "Decider unavailable"}
        }
        relay.outbound()
        self.assertEqual(self.people.reports, [{
            "id": "conversation", "outcomes": [],
            "refusal": {"code": "decider_unreachable", "message": "Decider unavailable"},
        }])
