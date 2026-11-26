"""Freeze recipients and answer policy before a shared send is attempted."""

from __future__ import annotations

from addresses import Addresses


def prepare_send(record: dict, addresses: Addresses) -> dict:
    mapped = {
        address: addresses.users[address.removeprefix("user:")]
        for address in record["addresses"]
        if address.startswith("user:") and address.removeprefix("user:") in addresses.users
    }
    groups = [address.removeprefix("group:") for address in record["addresses"]
              if address.startswith("group:")]
    if groups and len(record["addresses"]) != 1:
        return {"refusal": {"code": "unsupported_selector",
                            "message": "Send to one group or a list of users."}}

    missing = [
        {"address": address, "status": "not_reachable", "reason": "no_person_mapping"}
        for address in record["addresses"]
        if address not in mapped and not address.startswith("group:")
    ]
    rule = record["answer_rule"]
    policy = rule
    if rule and rule["kind"] == "named":
        decider = addresses.users.get(rule["address"].removeprefix("user:"))
        if decider is None or (not groups and decider not in mapped.values()):
            return {"refusal": {"code": "decider_unreachable",
                                "message": "The named decider must be reachable on this send."}}
        policy = {"kind": "named", "people": [decider]}

    selector = (
        {"kind": "group", "group": groups[0]} if groups
        else {"kind": "people", "people": list(mapped.values())}
    )
    return {
        "selector": selector,
        "mapped": mapped,
        "missing": missing,
        "organization": record.get("organization"),
        "title": record["title"],
        "body": record["body"],
        "choices": record["choices"],
        "answer_policy": policy,
    }


def delivery_outcomes(request: dict, wire_outcomes: list[dict]) -> list[dict]:
    by_person = {outcome["person_id"]: outcome["status"] for outcome in wire_outcomes}
    return request["missing"] + [
        {"address": address, "status": {"reached": "reached", "unreachable": "not_reachable"}[
            by_person[person_id]
        ]}
        for address, person_id in request["mapped"].items()
    ]
