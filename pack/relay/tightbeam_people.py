"""The relay-facing Tightbeam people-message commands."""

from __future__ import annotations

import json
import subprocess


class TightbeamPeople:
    def call(self, command: str, payload: dict) -> dict:
        result = subprocess.run(
            ["tightbeam", command, "--json", json.dumps(payload)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError(f"Tightbeam {command} exited {result.returncode}")
        return json.loads(result.stdout)

    def collect(self) -> list[dict]:
        return self.call("people-collect", {"limit": 100})["records"]

    def report(self, report: dict) -> None:
        self.call("people-report", report)

    def event(self, event: dict) -> None:
        self.call("people-event", event)
