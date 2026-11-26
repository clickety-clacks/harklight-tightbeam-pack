"""The relay-facing Tightbeam people-message commands."""

from __future__ import annotations

import json
import subprocess


class TightbeamPeople:
    def call(self, command: str, payload: dict) -> dict | None:
        result = subprocess.run(
            ["tightbeam", command, "--json", json.dumps(payload)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode:
            if command == "people-lookup":
                for output in (result.stdout, result.stderr):
                    try:
                        error = json.loads(output)
                    except ValueError:
                        continue
                    if isinstance(error, dict) and error.get("code") == "not_found":
                        return None
            raise RuntimeError(f"Tightbeam {command} exited {result.returncode}")
        return json.loads(result.stdout)

    def collect(self) -> list[dict]:
        return self.call("people-collect", {"limit": 100})["records"]

    def report(self, report: dict) -> None:
        self.accept("people-report", report)

    def event(self, event: dict) -> None:
        self.accept("people-event", event)

    def accept(self, command: str, payload: dict) -> None:
        response = self.call(command, payload)
        if response.get("accepted") is not True or type(response.get("duplicate")) is not bool:
            raise RuntimeError(f"Tightbeam {command} did not confirm acceptance")

    def lookup(self, server_id: str, item_id: str) -> dict | None:
        return self.call("people-lookup", {
            "server_id": server_id, "remote_conversation_id": item_id,
        })
