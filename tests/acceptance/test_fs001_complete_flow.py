"""T130 complete FS-001 acceptance gate.

The canonical fixture is a deterministic mixed-activity replay.  This gate
checks the complete recorded flow and its safety boundaries without claiming
that a live provider or merchant mutation was exercised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.observability.evaluation import build_evaluation_trace
from replay.runner import run_live_or_replay, run_replay
from replay.variants import run_variant


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_FIXTURE = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "canonical" / "incident.json"
)
ALLOWED_TERMINAL_STATES = {
    "verified_contained",
    "verified_failed",
    "escalated_unresolved",
}
EXPECTED_STAGES = {
    "incident",
    "evidence",
    "timeline",
    "attribution",
    "exposure",
    "proposal",
    "policy",
    "approval",
    "action",
    "reconciliation",
    "verification",
    "escalation",
    "terminal",
    "audit",
}


def _fixture() -> dict[str, Any]:
    return json.loads(CANONICAL_FIXTURE.read_text(encoding="utf-8"))


def _canonical_run() -> dict[str, Any]:
    fixture = _fixture()
    return run_replay(
        fixture=fixture,
        fixture_version=fixture["fixture_version"],
        deterministic_seed=fixture["deterministic_seed"],
    )


def test_complete_mixed_legitimate_attacker_flow_is_explicit_and_traceable() -> None:
    fixture = _fixture()
    first = _canonical_run()
    second = _canonical_run()

    # The full stage set is explicit, deterministic, and bound to the fixture.
    assert first == second
    assert set(first["stage_outcomes"]) == EXPECTED_STAGES
    assert all(
        isinstance(outcome, str) and outcome.strip()
        for outcome in first["stage_outcomes"].values()
    )
    assert not first["differences_from_expected"]
    assert first["tenant_id"] == fixture["tenant_id"]
    assert first["case_id"] == fixture["case_id"]
    assert first["correlation_id"] == fixture["correlation_id"]

    # Legitimate, malicious, and uncertain activity remain distinct.
    labels_by_event: dict[str, set[str]] = {}
    for attribution in first["attribution"]:
        labels_by_event.setdefault(attribution["timeline_event_id"], set()).add(
            attribution["label"]
        )
    assert {"malicious", "legitimate", "uncertain"} <= {
        label for labels in labels_by_event.values() for label in labels
    }
    assert labels_by_event["timeline-payment-legitimate-001"] == {"legitimate"}
    assert labels_by_event["timeline-payment-malicious-001"] == {"malicious"}
    assert labels_by_event["timeline-payment-uncertain-001"] == {"uncertain"}
    assert (
        first["attribution_labels"] == fixture["expected_results"]["attribution_labels"]
    )

    # Integer minor-unit exposure preserves legitimate value and remaining risk.
    expected_results = fixture["expected_results"]
    exposure = first["exposure"]
    for field in (
        "gross_exposure_minor",
        "recoverable_value_minor",
        "contained_value_minor",
        "legitimate_value_disrupted_minor",
        "remaining_exposure_minor",
    ):
        assert isinstance(exposure[field], int)
        assert exposure[field] == expected_results[field]
    assert exposure["currency"] == expected_results["currency"]
    assert exposure["uncertain_source_references"]

    # Policy and approval are version-bound, with separation of duties.
    policy = first["policy_decision"]
    approval = first["approval"]
    assert policy["result"] == "approval_required"
    assert policy["policy_version_id"] == fixture["policy_version_id"]
    assert policy["evaluated_conditions"]["uncertainty_preserved"] is True
    assert approval["status"] == "approved"
    assert approval["policy_version_id"] == policy["policy_version_id"]
    assert approval["required_for"] == "refund_payment:pay_canonical_malicious_001"
    assert approval["proposer_id"] != approval["approver_id"]
    assert approval["separation_of_duties"] is True

    # The action identity and targets survive the proposal/policy/action path.
    actions = first["action"]
    expected_actions = fixture["action"]
    for key in ("automatic_reversible", "approval_gated"):
        actual_action = actions[key]
        expected_action = expected_actions[key]
        assert {
            "proposal_id": actual_action["proposal_id"],
            "action_type": actual_action["action_type"],
            "target_resource": actual_action["target_resource"],
        } == {
            "proposal_id": expected_action["proposal_id"],
            "action_type": expected_action["action_type"],
            "target_resource": expected_action["target_resource"],
        }
    assert actions["simulation"] is True
    assert actions["remote_side_effects"] == []
    assert first["side_effects"] is False
    assert first["live_execution_occurred"] is False

    # UNKNOWN is reconciled before retry; verification is mandatory and its
    # inconclusive result produces the explicit escalation terminal state.
    reconciliation = first["reconciliation"]
    assert reconciliation == {
        "status": "reconciled_before_retry",
        "unknown_result": True,
        "retry_before_reconciliation": False,
    }
    verification = first["verification"]
    assert verification["verification_version"]
    assert verification["automatic_action"] == "verified_success"
    assert verification["approval_gated_action"] == "inconclusive"
    assert first["escalation"]["owner"]
    assert first["escalation"]["recommended_human_decision"]
    assert first["terminal_state"] == "escalated_unresolved"
    assert first["terminal_state"] in ALLOWED_TERMINAL_STATES

    # Every audit link is tenant/case/correlation scoped and checksum-linked.
    audit = first["audit"]
    assert {record["stage"] for record in audit} >= {
        link["stage"] for link in fixture["audit_links"]
    }
    assert all(
        record["tenant_id"] == fixture["tenant_id"]
        and record["case_id"] == fixture["case_id"]
        and record["correlation_ids"] == [fixture["correlation_id"]]
        and record["mode"] == record["label"] == "replay"
        and len(record["record_checksum"]) == 64
        for record in audit
    )
    assert audit[0]["previous_record_checksum"] is None
    assert all(
        current["previous_record_checksum"] == previous["record_checksum"]
        for previous, current in zip(audit, audit[1:])
    )

    # Evaluation traceability is bounded and remains non-authoritative.
    trace = build_evaluation_trace(
        tenant_id=first["tenant_id"],
        correlation_id=first["correlation_id"],
        case_id=first["case_id"],
        evaluation_run_id=first["run_id"],
        mode=first["mode"],
        live_execution_occurred=first["live_execution_occurred"],
        data={
            "fixture_version": first["fixture_version"],
            "policy_version_id": first["policy_version_id"],
            "outcome": first["terminal_state"],
            "action_reference": "proposal-canonical-hold-001",
            "audit_reference": audit[-1]["record_checksum"],
            "raw_evidence": "must not be retained",
            "held_out_seed": "must not be retained",
        },
    )
    assert trace["mode"] == trace["label"] == "replay"
    assert trace["non_authoritative"] is True
    assert trace["side_effects"] is False
    assert trace["trace_correlation"]["evaluation_run_id"] == first["run_id"]
    assert "raw_evidence" not in trace
    assert "held_out_seed" not in trace


def test_complete_flow_rejects_forbidden_and_cross_scope_paths() -> None:
    fixture = _fixture()
    forbidden = run_variant(
        variant="forbidden_proposal",
        fixture_version=fixture["fixture_version"],
        deterministic_seed=fixture["deterministic_seed"],
        mode="replay",
    )
    assert forbidden["outcome"] == "rejected"
    assert forbidden["side_effects"] is False
    assert not forbidden["remote_side_effects"]

    with pytest.raises(ValueError, match="tenant scope"):
        run_replay(
            fixture=fixture,
            fixture_version=fixture["fixture_version"],
            tenant_id="tenant-attacker-substitution",
            deterministic_seed=fixture["deterministic_seed"],
        )
    with pytest.raises(ValueError, match="case scope"):
        run_replay(
            fixture=fixture,
            fixture_version=fixture["fixture_version"],
            case_id="case-other-tenant",
            deterministic_seed=fixture["deterministic_seed"],
        )


def test_complete_flow_keeps_live_requests_truthful_and_operator_visible() -> None:
    fixture = _fixture()
    result = run_live_or_replay(
        mode="live",
        fixture=fixture,
        fixture_version=fixture["fixture_version"],
        deterministic_seed=fixture["deterministic_seed"],
    )
    assert result["requested_mode"] == "live"
    assert result["mode"] == result["label"] == "replay"
    assert result["provenance"]["effective_mode"] == "replay"
    assert result["provenance"]["final_mode"] == "replay"
    assert result["fallback_reason"]
    assert result["live_execution_occurred"] is False
    assert result["side_effects"] is False
    assert result["remote_side_effects"] == []

    ui_files = (
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "app"
        / "cases"
        / "[caseId]"
        / "page.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "CaseTimeline.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "ExposureSummary.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "ActionDecisionPanel.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "ApprovalPanel.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "case"
        / "EscalationPanel.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "replay"
        / "ReplayPanel.tsx",
        REPOSITORY_ROOT
        / "frontend"
        / "src"
        / "components"
        / "audit"
        / "AuditTrace.tsx",
    )
    source = "\n".join(path.read_text(encoding="utf-8").lower() for path in ui_files)
    for term in (
        "tenant",
        "legitimate",
        "malicious",
        "uncertain",
        "exposure",
        "approval",
        "escalation",
        "terminal",
        "audit",
        "replay",
        "live",
    ):
        assert term in source
    assert "delete" not in source
    assert "insert" not in source
    assert "update" not in source
