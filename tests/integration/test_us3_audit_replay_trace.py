"""T102 redacted replay trace coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TRACE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "audit"
    / "us3_containment_replay_trace.json"
)
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
REQUIRED_STAGES = {
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


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_keys(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value)) if value else set()
    return set()


def test_redacted_trace_links_authority_without_live_side_effects() -> None:
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    assert trace["mode"] == "replay"
    assert trace["label"] == "replay"
    assert "live" not in trace["fixture_provenance"]
    assert not (_keys(trace) & FORBIDDEN)
    stages = [item["stage"] for item in trace["chain"]]
    assert REQUIRED_STAGES.issubset(stages)
    assert all(len(item["checksum"]) == 64 for item in trace["chain"])
    terminal_outcomes = [
        item["outcome"] for item in trace["chain"] if item["stage"] == "terminal"
    ]
    assert terminal_outcomes == ["verified_contained", "escalated_unresolved"]
    executions = [item for item in trace["chain"] if item["stage"] == "execution"]
    assert len(executions) == 2
    assert executions[1]["reconciliation"] == "reconciled-before-retry"
