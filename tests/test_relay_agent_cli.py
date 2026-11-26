from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pack" / "relay"))

from agent_cli import AgentCLI


class AgentCLITests(unittest.TestCase):
    def setUp(self):
        self.cli = AgentCLI("/example/identity", Path("/example/state"))

    def test_new_mutation_requires_proof_it_is_absent_from_original_journal(self):
        absent = {"kind": "operation_absent", "op_id": "op", "journal_id": "journal"}
        committed = {"kind": "committed", "op_id": "op", "response": {"rev": 3}}
        with patch.object(self.cli, "run", side_effect=[(1, [absent]), (0, [committed])]) as run:
            self.assertEqual(self.cli.mutation("journal", "op", ["send"]), committed)
        self.assertEqual(run.call_args_list[0].args,
                         ("retry", "--op-id", "op", "--journal-id", "journal"))
        self.assertEqual(run.call_args_list[1].args, ("send", "--op-id", "op"))

    def test_unresolved_mutation_does_not_prepare_a_new_operation(self):
        unknown = {"kind": "outcome_unknown", "op_id": "op"}
        with patch.object(self.cli, "run", return_value=(7, [unknown])) as run:
            with self.assertRaisesRegex(RuntimeError, "unresolved"):
                self.cli.mutation("journal", "op", ["send"])
            run.assert_called_once()

    def test_same_operation_refusal_is_returned_to_caller(self):
        refused = {"kind": "refused", "op_id": "op", "error": "recipient_refused"}
        with patch.object(self.cli, "run", return_value=(2, [refused])) as run:
            self.assertEqual(self.cli.mutation("journal", "op", ["send"]), refused)
            run.assert_called_once()
