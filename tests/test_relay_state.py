from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pack" / "relay"))

from addresses import Addresses
from relay_state import RelayState


class RelayStateTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "relay.db"

    def open_state(self):
        return RelayState(self.path, "connection", "sender")

    def test_retry_keeps_prepared_recipients_and_operation_id(self):
        state = self.open_state()
        original = state.prepare("record", lambda: {"person": "recipient-a"})
        session = state.session_id()
        state.close()

        state = self.open_state()
        self.addCleanup(state.close)
        replay = state.prepare("record", lambda: self.fail("mapping was resolved again"))
        self.assertEqual(tuple(replay), tuple(original))
        self.assertEqual(json.loads(replay["request"]), {"person": "recipient-a"})
        self.assertEqual(state.session_id(), session)

    def test_event_and_acknowledged_checkpoint_survive_restart(self):
        state = self.open_state()
        state.advance({"rev": 4})
        event = {"speaker": {"address": "user:writer", "display_name": "Writer"}}
        state.prepare_event(event)
        state.close()

        state = self.open_state()
        self.addCleanup(state.close)
        self.assertEqual(state.checkpoint(), {"rev": 4})
        self.assertEqual(state.pending_event(), event)
        state.complete_event({"rev": 5})
        self.assertIsNone(state.pending_event())
        self.assertEqual(state.checkpoint(), {"rev": 5})

    def test_attribution_uses_person_id_and_preserves_outside_identity(self):
        addresses = Addresses({"writer": "person-1"})
        mapped = {"kind": "person", "id": "person-1", "display_name": "Renamed"}
        outside = {"kind": "person", "id": "writer", "display_name": "Writer"}
        self.assertEqual(
            addresses.speaker("service", mapped),
            {"address": "user:writer", "display_name": "Renamed"},
        )
        self.assertEqual(
            addresses.speaker("service", outside),
            {"server_id": "service", "person_id": "writer", "display_name": "Writer"},
        )
