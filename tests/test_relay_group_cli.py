from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pack" / "relay"))

from harklight_agent import HarklightAgent


class GroupCLITests(unittest.TestCase):
    def setUp(self):
        self.cli = MagicMock()
        self.cli.supports_groups.return_value = True
        self.cli.one.side_effect = [
            {"journal_id": "journal"},
            {"server_id": "example", "shared_messages": True, "groups": True},
        ]
        state = MagicMock()
        state.session_id.return_value = "session"
        self.agent = HarklightAgent(self.cli, "product:relay", state)

    def test_one_selector_and_named_decider(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload.json"
            for key, value, flag in [
                ("name", "Local Team", "--group-name=Local Team"),
                ("group_id", "opaque-id", "--group-id=opaque-id"),
            ]:
                args = self.agent.send_args({
                    "selector": {"kind": "group", key: value},
                    "answer_policy": {"kind": "named", "people": ["person"]},
                    "choices": [], "title": "Request", "body": "Body",
                }, payload)
                self.assertIn(flag, args)
                self.assertNotIn("--person-id", args)
                self.assertNotIn("--organization", args)
                self.assertEqual(args[args.index("--decider-id") + 1], "person")

    def test_group_scope_starts_fresh_and_uses_one_continuation(self):
        self.cli.one.side_effect = None
        self.cli.one.return_value = {
            "kind": "baseline_prepared", "shared_events": True, "rev": 20,
            "continuation": "group-scope", "token": "pending",
        }
        self.cli.run.return_value = (0, [{"kind": "baseline_complete", "rev": 20}])
        checkpoints = list(self.agent.changes({"rev": 19, "continuation": "shared-only"}))
        self.cli.one.assert_called_with("read", "--groups", "--session", "session",
                                        "--ack2", "--pending", "--prepare")
        self.cli.run.assert_called_with("read", "--groups", "--session", "session", "--ack2",
                                        "--pending", "--resume", "pending")
        self.assertEqual(checkpoints[-1], (
            "example", None, {"rev": 20, "continuation": "group-scope", "groups": True},
        ))
        self.assertIn("--groups", self.agent.follow_args(checkpoints[-1][2]))
        self.assertNotIn("--shared", self.agent.follow_args(checkpoints[-1][2]))
        self.cli.run.return_value = (0, [{"kind": "caught_up", "rev": 21}])
        list(self.agent.changes(checkpoints[-1][2]))
        self.cli.run.assert_called_with("read", "--groups", "--session", "session", "--ack2",
                                        "--after", "20", "--continuation", "group-scope")

    def test_old_cli_on_group_capable_server_keeps_named_feed_working(self):
        self.cli.one.side_effect = [
            {"journal_id": "journal"},
            {"server_id": "example", "shared_messages": True, "groups": True},
        ]
        self.cli.supports_groups.return_value = False
        state = MagicMock()
        state.session_id.return_value = "session"
        agent = HarklightAgent(self.cli, "product:relay", state)
        self.cli.run.return_value = (0, [{"kind": "caught_up", "rev": 21}])
        list(agent.changes({"rev": 20, "continuation": "shared-only"}))
        self.cli.run.assert_called_with("read", "--shared", "--session", "session", "--ack2",
                                        "--after", "20", "--continuation", "shared-only")

    def test_group_update_uses_the_conversation_and_group_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload.json"
            args = self.agent.conversation_args({
                "item_id": "shared-item", "kind": "update", "groups": True,
                "base_revision": 3, "message": {"title": "Revised"},
            }, payload)
            self.assertEqual(args, [
                "revise", "--groups", "--item-id", "shared-item", "--base-revision", "3",
                "--message-json", str(payload),
            ])
            self.assertTrue(payload.is_file())

    def test_group_answer_receipt_retains_scope(self):
        self.cli.mutation.return_value = {"kind": "committed"}
        self.agent.receipt("op", {
            "kind": "answer", "event_id": "answer", "remote_conversation_id": "shared",
            "groups": True,
        })
        self.cli.mutation.assert_called_once_with(
            "journal", "op", ["receipt", "--item-id", "shared", "--groups", "--answer-id", "answer"],
        )
