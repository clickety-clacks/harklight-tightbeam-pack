from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


RELAY = Path(__file__).resolve().parents[1] / "pack" / "relay" / "relay.py"
FIXTURE = Path(__file__).parent / "fixtures" / "relay-cli.py"


class SubprocessRelayTests(unittest.TestCase):
    def test_send_baseline_acceptance_and_receipt_use_the_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for cli in ("tightbeam", "harklight-agent"):
                script = root / cli
                script.write_text(f"#!{sys.executable}\n" + FIXTURE.read_text(), encoding="utf-8")
                script.chmod(0o700)

            config = root / "config.json"
            config.write_text(json.dumps({
                "connection": str(root / "identity"),
                "sender": "product:relay",
                "users": {"reader": "person-a"},
            }), encoding="utf-8")
            environment = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                           "RELAY_FIXTURE_ROOT": str(root)}
            for _ in range(2):
                result = subprocess.run(
                    [sys.executable, str(RELAY), "--config", str(config),
                     "--state-dir", str(root / "state")],
                    env=environment, capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            log = (root / "log").read_text().splitlines()
            self.assertEqual(log, ["sent", "reported", "event", "receipt", "resumed"])
