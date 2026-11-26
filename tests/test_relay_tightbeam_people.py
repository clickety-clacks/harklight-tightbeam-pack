from pathlib import Path
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pack" / "relay"))

from tightbeam_people import TightbeamPeople


class TightbeamLookupTests(unittest.TestCase):
    def test_only_machine_not_found_is_an_unknown_conversation(self):
        for status, code, expected_unknown in (
            (404, "not_found", True), (500, "not_found", False),
            (404, "gateway_unavailable", False),
        ):
            with self.subTest(status=status, code=code):
                error = {"ok": False, "httpStatus": status, "error": {"code": code}}
                result = subprocess.CompletedProcess(
                    ["tightbeam"], 1, stdout="", stderr="Lookup refused\n" + json.dumps(error)
                )
                with patch("tightbeam_people.subprocess.run", return_value=result):
                    if expected_unknown:
                        self.assertIsNone(TightbeamPeople().lookup("example", "conversation"))
                    else:
                        with self.assertRaises(RuntimeError):
                            TightbeamPeople().lookup("example", "conversation")
