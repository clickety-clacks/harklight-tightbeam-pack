import fcntl
import json
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pack" / "relay"))

from addresses import Addresses
from harklight_agent import HarklightAgent
from relay import Relay
from relay_process import RelayProcess
from relay_state import RelayState
from relay_watch import OUTBOUND_BATCH, RelayWatch, readiness_failure
from test_relay import ANSWER, AgentFixture, PeopleFixture


class ReadinessTests(unittest.TestCase):
    def test_idle_boundary_and_report_unblock_trigger_collect_and_drain(self):
        relay = MagicMock()
        relay.outbound.side_effect = [False, True, True, False]
        watch = RelayWatch(relay)
        self.addCleanup(watch.selector.close)
        with patch("relay_watch.RelayProcess") as child:
            child.return_value.result.return_value = (0, "")
            watch.start_readiness()
            self.assertEqual(relay.outbound.call_count, 1)
            watch.readiness([{"records": []}], True)
            self.assertEqual(relay.outbound.call_count, 1)
            # The send appeared while replacing the old idle wait. The new
            # wait sees it, and reporting it makes the next collect eligible.
            watch.readiness([{"records": [{"id": "send"}]}], True)
            self.assertEqual(relay.outbound.call_count, 2)
            watch.start_readiness()
            watch.start_readiness()
            self.assertEqual(relay.outbound.call_count, 4)
            self.assertEqual(child.call_count, 3)
            watch.close_child("readiness")

    def test_only_exact_compatibility_and_broker_errors_retry(self):
        legacy = "unknown command: people-wait — run 'tightbeam help' for usage. Commands: ask"
        self.assertEqual(readiness_failure(1, legacy), "unsupported")
        self.assertIsNone(readiness_failure(2, legacy))
        self.assertIsNone(readiness_failure(1, legacy + '\n{"other":true}'))

        def stderr(status, code, message=""):
            return "Refused\n" + json.dumps({
                "httpStatus": status, "error": {"code": code, "message": message},
            })

        self.assertEqual(readiness_failure(1, stderr(400, "invalid_message", "verb not allowed: people-wait")),
                         "unsupported")
        self.assertEqual(readiness_failure(1, stderr(503, "people_readiness_unavailable")), "retry")
        for status, code in [
            (403, "forbidden"), (403, "people_messaging_not_enabled"),
            (400, "invalid"), (400, "invalid_message"),
            (503, "gateway_unavailable"), (400, "people_readiness_unavailable"),
        ]:
            with self.subTest(code=code, status=status):
                self.assertIsNone(readiness_failure(1, stderr(status, code)))

    def test_unsupported_wait_uses_a_single_bounded_collect_path(self):
        relay = MagicMock()
        relay.outbound.return_value = False
        watch = RelayWatch(relay)
        self.addCleanup(watch.selector.close)
        with patch("relay_watch.RelayProcess") as child:
            child.return_value.result.return_value = (
                1, "unknown command: people-wait — run 'tightbeam help' for usage. Commands: ask",
            )
            watch.start_readiness()
            watch.readiness([], True)
            self.assertNotIn("readiness", watch.children)
            watch.start_readiness()
            self.assertEqual(relay.outbound.call_count, 2)
            child.assert_called_once()

    def test_readiness_reads_one_pretty_printed_json_result(self):
        with selectors.DefaultSelector() as selector:
            process = RelayProcess(selector, [
                sys.executable, "-c",
                "import json; print(json.dumps({'records': [{'id': 'one'}]}, indent=2))",
            ], "readiness")
            try:
                self.assertTrue(selector.select(5))
                self.assertEqual(process.frames(), ([], False))
                self.assertTrue(selector.select(5))
                self.assertEqual(process.frames(), ([{"records": [{"id": "one"}]}], True))
                self.assertEqual(process.result(), (0, ""))
            finally:
                process.close()

    def test_locked_state_preserves_finite_noop_and_rejects_second_watcher(self):
        script = Path(__file__).resolve().parents[1] / "pack" / "relay" / "relay.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({"users": {}, "connection": str(root), "sender": "sender"}))
            with (root / "run.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                for mode, exit_status in (([], 0), (["--watch"], 1)):
                    result = subprocess.run(
                        [sys.executable, str(script), "--config", str(config),
                         "--state-dir", str(root), *mode], capture_output=True, text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, exit_status)
                    if mode:
                        self.assertIn("another relay already owns this state directory", result.stderr)
                    else:
                        self.assertEqual(result.stderr, "")
                    self.assertFalse((root / "relay.db").exists())

    def test_always_ready_outbound_yields_to_listener_and_receipts(self):
        relay = MagicMock()
        relay.outbound.side_effect = [True, True, AssertionError("outbound did not yield")]
        relay.agent.server_id = "server"
        relay.agent.follow_args.return_value = ["fixture"]
        relay.state.checkpoint.return_value = {"rev": 19, "continuation": "scope"}
        relay.apply_change.return_value = True
        watch = RelayWatch(relay)
        self.addCleanup(watch.selector.close)
        with patch("relay_watch.RelayProcess") as child, patch.object(
            watch.selector, "select", return_value=[(MagicMock(data="listener"), 1)]
        ):
            child.return_value.frames.return_value = ([ANSWER], False)
            watch.tick()
            watch.tick()
            relay.inbound.assert_called_once()
            self.assertEqual(relay.outbound.call_count, 2)
            relay.outbound.assert_called_with(limit=OUTBOUND_BATCH)
            self.assertEqual(relay.apply_change.call_count, 2)
            relay.receipts.assert_called()
            watch.close_child("listener")

    def test_group_reconnect_keeps_feed_scope_in_durable_checkpoints(self):
        relay = MagicMock()
        relay.outbound.return_value = False
        relay.apply_change.return_value = True
        relay.agent.server_id = "example"
        relay.agent.follow_args.return_value = ["fixture"]
        relay.state.checkpoint.return_value = {
            "rev": 19, "continuation": "group-scope", "groups": True,
        }
        watch = RelayWatch(relay)
        self.addCleanup(watch.selector.close)
        watch.listener_started = True
        with patch("relay_watch.RelayProcess"):
            watch.start_listener()
            watch.listener([ANSWER], False)
            relay.agent.refresh_capabilities.assert_called_once()
            relay.agent.follow_args.assert_called_once_with({
                "rev": 19, "continuation": "group-scope", "groups": True,
            })
            relay.apply_change.assert_called_once_with("example", ANSWER, {
                "rev": 20, "continuation": "group-scope", "groups": True,
            })
            watch.close_child("listener")

    def test_listener_logs_expiry_before_reset(self):
        relay = MagicMock()
        watch = RelayWatch(relay)
        self.addCleanup(watch.selector.close)
        with patch("relay_watch.report_retention_gap") as report:
            def advance(position):
                self.assertIsNone(position)
                report.assert_called_once()

            relay.state.advance.side_effect = advance
            watch.listener([{"kind": "cursor_expired", "rev": 9}], True)
            relay.state.advance.assert_called_once_with(None)

    def test_finite_read_logs_expiry_before_emitting_reset(self):
        cli = MagicMock()
        cli.one.side_effect = [
            {"journal_id": "journal"}, {"server_id": "server", "shared_messages": True},
        ]
        cli.run.return_value = (2, [{"kind": "cursor_expired", "rev": 9}])
        agent = HarklightAgent(cli, "sender", MagicMock())
        with patch("harklight_agent.report_retention_gap") as report:
            changes = agent.changes({"rev": 9, "continuation": "scope"})
            self.assertEqual(next(changes), ("server", None, None))
            report.assert_called_once()

    def test_child_disconnect_discards_partial_frame(self):
        with selectors.DefaultSelector() as selector:
            process = RelayProcess(selector, [
                sys.executable, "-c", "import sys; sys.stdout.write('{\"kind\":'); sys.stdout.flush()",
            ], "listener")
            self.addCleanup(process.close)
            self.assertTrue(selector.select(5))
            self.assertEqual(process.frames(), ([], False))
            self.assertTrue(selector.select(5))
            with self.assertRaisesRegex(RuntimeError, "incomplete JSON"):
                process.frames()


class SenderRecoveryTests(unittest.TestCase):
    def test_disconnect_after_acceptance_replays_pending_before_listening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "relay.db"
            state = RelayState(path, "connection", "sender")
            people = PeopleFixture()
            agent = AgentFixture()
            agent.server_id = "service"
            relay = Relay(state, Addresses({"reader": "person-1"}), people, agent)
            relay.outbound()
            state.advance({"rev": 19, "continuation": "scope"})

            watched = RelayWatch(relay)
            with patch.object(state, "complete_event", side_effect=RuntimeError("interrupted")):
                watched.listener_scope = {"continuation": "scope"}
                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    watched.listener([ANSWER], False)
            first = people.events[0]
            self.assertEqual(state.checkpoint()["rev"], 19)
            self.assertIsNotNone(state.pending_event())
            watched.selector.close()
            state.close()

            restarted = RelayState(path, "connection", "sender")
            self.addCleanup(restarted.close)
            relay = Relay(restarted, Addresses({"changed": "person-1"}), people, agent)
            watch = RelayWatch(relay)
            self.addCleanup(watch.selector.close)
            agent.changes = lambda _: iter(())
            agent.follow_args = MagicMock(return_value=["fixture"])
            with patch("relay_watch.RelayProcess"):
                watch.start_listener()
                watch.close_child("listener")
            self.assertEqual(people.events, [first, first])
            self.assertIsNone(restarted.pending_event())
            self.assertEqual(restarted.checkpoint(), {"rev": 20, "continuation": "scope"})
            self.assertEqual(len(restarted.receipts()), 1)
            self.assertEqual(restarted.receipts()[0]["event"], json.dumps(first))
            agent.follow_args.assert_called_once_with({"rev": 20, "continuation": "scope"})
