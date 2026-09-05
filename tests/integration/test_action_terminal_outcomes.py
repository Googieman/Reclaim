"""T102: every replayed attempted action has an explicit terminal outcome."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TRACE = Path(__file__).parents[1] / "fixtures" / "audit" / "containment_trace.json"
ALLOWED_TERMINALS = {"verified_contained", "verified_failed", "escalated_unresolved"}
FORBIDDEN = {
    "secret",
    "credential",
    "password",
    "authorization",
    "raw_payload",
    "pii",
    "email",
    "phone",
}


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_keys(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value)) if value else set()
    return set()


def test_every_attempted_action_ends_in_an_explicit_terminal_outcome() -> None:
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    assert trace["mode"] == "replay"
    assert trace["label"] == "replay"
    assert not (_keys(trace) & FORBIDDEN)
    chain = trace["chain"]
    assert {item["stage"] for item in chain} >= {
        "incident",
        "evidence",
        "attribution",
        "exposure",
        "proposal",
        "policy",
        "approval",
        "canonical_action",
        "execution",
        "verification",
        "escalation",
        "terminal",
    }
    executions = {item["id"] for item in chain if item["stage"] == "execution"}
    terminal_outcomes = {
        item["outcome"] for item in chain if item["stage"] == "terminal"
    }
    assert executions == {"execution-001", "execution-002"}
    assert terminal_outcomes == {"verified_contained", "escalated_unresolved"}
    assert terminal_outcomes <= ALLOWED_TERMINALS
    assert all(len(item["checksum"]) == 64 for item in chain)
    terminals_by_execution = {
        item["execution_id"]: item["outcome"]
        for item in chain
        if item["stage"] == "terminal"
    }
    assert terminals_by_execution == {
        "execution-001": "verified_contained",
        "execution-002": "escalated_unresolved",
    }
