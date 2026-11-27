from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pack" / "relay"))

from addresses import Addresses
from projection import event_for


class ProjectionTests(unittest.TestCase):
    def test_answer_uses_answer_id_and_durable_person_id(self):
        terminal = {
            "state": "answered",
            "at_ms": 300,
            "answer": "thu",
            "outcome": {"kind": "choice", "id": "thu", "label": "Thursday"},
            "answer_id": "answer_a",
            "speaker": {"kind": "person", "id": "person_d", "display_name": "Dana"},
        }
        change = {
            "rev": 81,
            "kind": "answer",
            "data": {
                "item_id": "shared_a",
                "answer_id": "answer_a",
                "request_revision": 2,
                "person_id": "person_d",
                "terminal": terminal,
            },
        }
        addresses = Addresses({"reader": "person_d"})
        self.assertEqual(
            event_for("server", change, addresses),
            {
                "server_id": "server",
                "remote_conversation_id": "shared_a",
                "event_id": "answer_a",
                "kind": "answer",
                "remote_revision": 2,
                "speaker": {"address": "user:reader", "display_name": "Dana"},
                "content": {"answer": "thu"},
            },
        )
        message = {"kind": "message", "data": {"item_id": "shared_a", "terminal": terminal}}
        self.assertIsNone(event_for("server", message, addresses))
