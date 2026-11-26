"""Fake the public Agent and Tightbeam relay commands against contract fixtures."""

import json
import os
from pathlib import Path
import sys


root = Path(os.environ["RELAY_FIXTURE_ROOT"])
log = root / "log"
journal = "c151d0f7-c65e-47c3-af88-18f1591389d6"
answer = {
    "kind": "answer",
    "rev": 3,
    "data": {
        "item_id": "shared",
        "answer_id": "answer-a",
        "person_id": "person-a",
        "request_revision": 1,
        "terminal": {
            "answer": "yes",
            "speaker": {"kind": "person", "id": "person-a", "display_name": "Reader"},
        },
    },
}


def record(label):
    with log.open("a") as output:
        output.write(label + "\n")


def emit(value):
    print(json.dumps(value))


def value(args, flag):
    return args[args.index(flag) + 1]


if Path(sys.argv[0]).name == "tightbeam":
    command, json_flag, raw = sys.argv[1:]
    assert json_flag == "--json"
    payload = json.loads(raw)
    if command == "people-collect":
        rows = [] if log.exists() else [{
            "id": "message", "conversation_id": "message", "kind": "send",
            "addresses": ["user:reader"], "title": "Ready?", "body": "Review the result",
            "choices": [{"id": "yes", "label": "Approve"}],
            "answer_rule": {"kind": "named", "address": "user:reader"},
        }]
        emit({"records": rows})
    elif command == "people-report":
        assert payload == {
            "id": "message", "outcomes": [{"address": "user:reader", "status": "reached"}],
            "server_id": "example-server", "remote_conversation_id": "shared",
            "remote_revision": 1,
        }
        record("reported")
        emit({"accepted": True, "duplicate": False})
    elif command == "people-lookup":
        assert payload == {"server_id": "example-server", "remote_conversation_id": "shared"}
        emit({"conversation_id": "message", "revisions": [{"remote_revision": 1, "revision": 1}]})
    elif command == "people-event":
        assert log.read_text().splitlines()[-1] == "reported"
        assert payload == {
            "server_id": "example-server", "remote_conversation_id": "shared",
            "event_id": "answer-a", "kind": "answer", "remote_revision": 1,
            "speaker": {"address": "user:reader", "display_name": "Reader"},
            "content": {"answer": "yes"},
        }
        record("event")
        emit({"accepted": True, "duplicate": False})
    else:
        raise AssertionError(command)
else:
    assert sys.argv[1] == "--identity-dir"
    assert sys.argv[3] == "--state-dir"
    command, *args = sys.argv[5:]
    if command == "journal-id":
        emit({"kind": "journal", "journal_id": journal})
    elif command == "capabilities":
        emit({"server_id": "example-server", "shared_messages": True})
    elif command == "retry":
        assert value(args, "--journal-id") == journal
        emit({"kind": "operation_absent", "op_id": value(args, "--op-id"), "journal_id": journal})
        sys.exit(1)
    elif command == "send":
        op = value(args, "--op-id")
        if "--prepare" in args:
            assert value(args, "--person-id") == "person-a"
            assert value(args, "--decider-id") == "person-a"
            assert value(args, "--sender-id") == "product:relay"
            assert json.loads(Path(value(args, "--choices-json")).read_text()) == [
                {"id": "yes", "label": "Approve"},
            ]
            (root / "prepared").write_text(op)
            (root / "session").write_text(value(args, "--session"))
            emit({"kind": "prepared", "op_id": op})
        else:
            assert "--execute" in args
            assert op == (root / "prepared").read_text()
            record("sent")
            emit({
                "kind": "committed", "op_id": op, "item_id": "shared",
                "response": {"rev": 2, "message": {"revision": 1, "shared": {"shared_id": "shared"}},
                             "recipients": [{"person_id": "person-a", "status": "reached"}]},
            })
    elif command == "read":
        assert "--shared" in args and "--ack2" in args
        assert value(args, "--session") == (root / "session").read_text()
        if "--prepare" in args:
            emit({"kind": "baseline_prepared", "rev": 4, "token": "pending",
                  "continuation": "continuation", "shared_events": True})
        elif "--resume" in args:
            assert value(args, "--resume") == "pending"
            emit({"kind": "baseline", "rev": 4})
            emit(answer)
            emit({"kind": "baseline_complete", "rev": 4})
        else:
            assert value(args, "--after") == "4"
            assert value(args, "--continuation") == "continuation"
            record("resumed")
            emit({"kind": "caught_up", "rev": 5})
    elif command == "receipt":
        assert log.read_text().splitlines()[-1] == "event"
        assert value(args, "--item-id") == "shared"
        assert value(args, "--answer-id") == "answer-a"
        record("receipt")
        emit({"kind": "committed", "op_id": value(args, "--op-id"), "response": {"rev": 5}})
    else:
        raise AssertionError(command)
