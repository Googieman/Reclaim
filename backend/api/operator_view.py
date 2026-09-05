"""Replay-backed operator read model for the source-built demonstration runtime.

This adapter deliberately does not pretend that fixture data is authoritative
merchant state.  It reshapes a deterministic replay result for the operator UI
and labels that boundary in every response.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from replay.mode_selection import ModeSelection
from replay.runner import CANONICAL_FIXTURE_VERSION, ReplayRunner

CANONICAL_TENANT_ID = "tenant-canonical-demo"
CANONICAL_CASE_ID = "case-canonical-demo-001"


def build_operator_view(
    *,
    tenant_id: str,
    case_id: str,
    runner: ReplayRunner,
    mode: ModeSelection,
) -> dict[str, Any]:
    """Return the canonical replay as the UI's explicitly non-authoritative view."""

    if tenant_id != CANONICAL_TENANT_ID or case_id != CANONICAL_CASE_ID:
        raise LookupError("canonical replay case was not found in this tenant scope")

    result = runner.run(
        tenant_id=tenant_id,
        case_id=case_id,
        fixture_version=CANONICAL_FIXTURE_VERSION,
        deterministic_seed="canonical-seed-001",
        mode="replay",
    )
    timestamp = _data_timestamp(result)
    labels = dict(result.get("attribution_labels", {}))
    timeline = [_timeline_item(item, labels) for item in result.get("timeline", [])]
    exposure = _exposure(result)
    action_source = dict(result.get("action", {}))
    gated_action = dict(action_source.get("approval_gated", {}))
    approval = dict(result.get("approval", {}))
    verification_source = dict(result.get("verification", {}))
    escalation_source = dict(result.get("escalation", {}))

    return {
        "case": {
            "case_id": case_id,
            "tenant_id": tenant_id,
            "incident_id": "incident-canonical-demo-001",
            "merchant_name": "RECLAIM canonical demo merchant",
            "state": result.get("terminal_state", "escalated_unresolved"),
            "owner_id": escalation_source.get("owner", "merchant-ops-canonical"),
            "severity": "high",
            "last_refreshed_at": timestamp,
        },
        "reported_incident": {
            "source": "canonical-replay-fixture",
            "incident_type": "account_takeover",
            "occurred_at": timestamp,
            "customer_reference": "customer-canonical-001",
            "account_reference": "account-canonical-001",
            "order_reference": None,
            "payment_reference": "pay_canonical_malicious_001",
            "reported_amount_minor": exposure["gross_exposure_minor"],
            "reported_currency": exposure["currency"],
            "external_reference": None,
            "report_reference": "minio://replay-fixture/canonical-001",
            "narrative_checksum": None,
            "reported_value_status": "unverified",
        },
        "orchestration": None,
        "timeline": timeline,
        "exposure": exposure,
        "proposal": _proposal(gated_action, exposure),
        "policy_decision": result.get("policy_decision"),
        "approval": {
            **approval,
            "expected_version": 0,
            "reason": "Recorded fixture decision; no approval command is available in REPLAY.",
        },
        "action": {
            "status": gated_action.get("execution", "simulated_not_executed_without_live_gateway"),
            "execution_id": "execution-canonical-refund-001",
            "attempt_count": 0,
            "reconciliation_state": dict(result.get("reconciliation", {})).get("status"),
            "verification_state": verification_source.get("approval_gated_action"),
            "remote_reference": None,
            "result_reference": None,
        },
        "verification": {
            "status": _verification_status(verification_source),
            "observed_resource_state": "canonical replay fixture only",
            "verifier_source": "replay-fixture",
            "verification_version": verification_source.get(
                "verification_version", "verification-v1.0.0"
            ),
            "evidence_references": [],
            "recorded_at": timestamp,
            "checksum": result.get("provenance", {}).get("run_checksum"),
        },
        "escalation": {
            "escalation_id": escalation_source.get("escalation_id"),
            "state": "escalated_unresolved",
            "owner_id": escalation_source.get("owner"),
            "reason": escalation_source.get("reason", "Replay verification is inconclusive"),
            "remaining_exposure_minor": int(
                escalation_source.get(
                    "remaining_exposure_minor", exposure["remaining_exposure_minor"]
                )
            ),
            "currency": escalation_source.get("currency", exposure["currency"]),
            "evidence_references": [],
            "recommended_human_decision": escalation_source.get(
                "recommended_human_decision", "Review merchant state before any action"
            ),
            "expected_version": 0,
            "policy_version_id": result.get("policy_version_id"),
        },
        "audit": _audit_records(result, timestamp),
        "mode": mode.to_dict(),
        "evaluation": {
            "label": "replay",
            "fixture_version": result["fixture_version"],
            "dataset_version": "canonical-demo-v1.0.0",
            "provenance": {
                "production_data": False,
                "source": "merchant-controlled deterministic fixture",
                "run_id": result["run_id"],
            },
            "confidence_interval_metadata": {},
        },
        "next_human_decision": (
            "Inspect the trace; connect qualified merchant systems before taking any action."
        ),
        "data_as_of": timestamp,
        "read_only": True,
        "authoritative": False,
        "remote_side_effects": [],
    }


def create_operator_view_router(*, runner: ReplayRunner, mode: ModeSelection) -> Any:
    """Create the tenant/case-scoped read-only demonstration route."""

    from fastapi import APIRouter, HTTPException

    router = APIRouter()

    @router.get("/tenants/{tenant_id}/cases/{case_id}/operator-view")
    def operator_view(tenant_id: str, case_id: str) -> dict[str, Any]:
        try:
            return build_operator_view(
                tenant_id=tenant_id,
                case_id=case_id,
                runner=runner,
                mode=mode,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def _data_timestamp(result: dict[str, Any]) -> str:
    timestamps = [
        str(item.get("received_at") or item.get("effective_at") or "")
        for item in result.get("timeline", [])
    ]
    return max((value for value in timestamps if value), default="2026-09-01T09:03:02Z")


def _timeline_item(item: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    payload = dict(item.get("event_payload") or item.get("payload") or {})
    event_id = str(item["event_id"])
    value = {
        **item,
        "event_id": event_id,
        "occurred_at": item.get("effective_at") or item.get("occurred_at"),
        "attribution": labels.get(event_id, "uncertain"),
        "rationale": "Deterministic replay attribution",
        "evidence_references": list(item.get("evidence_references", [])),
        "provenance": {
            "method": "deterministic-replay",
            "version": "canonical-v1.0.0",
            "source": item.get("source_identity", "replay-fixture"),
        },
        "financial_impact_minor": payload.get("amount_minor"),
        "currency": payload.get("currency"),
        "uncertainty_reasons": list(item.get("uncertainty_reasons", [])),
        "source_event_ids": list(item.get("source_event_ids", [])),
    }
    if value["currency"] is None:
        del value["currency"]
    return value


def _exposure(result: dict[str, Any]) -> dict[str, Any]:
    source = dict(result.get("exposure", {}))
    value = {
        **source,
        "currency": source.get("currency", "INR"),
        "gross_exposure_minor": int(source.get("gross_exposure_minor", 0)),
        "recoverable_value_minor": int(source.get("recoverable_value_minor", 0)),
        "contained_value_minor": int(source.get("contained_value_minor", 0)),
        "legitimate_value_disrupted_minor": int(source.get("legitimate_value_disrupted_minor", 0)),
        "irreversible_loss_minor": int(source.get("irreversible_loss_minor", 0)),
        "remaining_exposure_minor": int(source.get("remaining_exposure_minor", 0)),
        "calculation_version": source.get("calculation_version", "exposure-v1.0.0"),
        "source_references": list(source.get("source_references", [])),
        "by_currency": [],
    }
    return value


def _proposal(action: dict[str, Any], exposure: dict[str, Any]) -> dict[str, Any]:
    return {
        "proposal_id": action.get("proposal_id", "proposal-canonical-refund-001"),
        "action_type": action.get("action_type", "refund_payment"),
        "target_resource": action.get("target_resource", "pay_canonical_malicious_001"),
        "amount_minor": exposure["recoverable_value_minor"],
        "currency": exposure["currency"],
        "rationale": "Canonical replay proposal; never submitted to a live gateway.",
        "evidence_references": list(exposure.get("source_references", [])),
        "current_resource_state": "captured in fixture",
        "reversibility": "financial action; approval and live gateway required",
        "customer_impact": "No impact in REPLAY",
        "proposer_id": "analysis-canonical-demo-001",
    }


def _verification_status(source: dict[str, Any]) -> str:
    value = source.get("approval_gated_action", "inconclusive")
    if value in {"verified_success", "verified_failure", "inconclusive"}:
        return str(value)
    if value == "verified_failed":
        return "verified_failure"
    return "inconclusive"


def _audit_records(result: dict[str, Any], timestamp: str) -> list[dict[str, Any]]:
    end = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(UTC)
    records = list(result.get("audit", []))
    start = end - timedelta(seconds=max(len(records) - 1, 0))
    output: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        stage = str(record.get("stage", "replay"))
        output.append(
            {
                **record,
                "recorded_at": (start + timedelta(seconds=index))
                .isoformat()
                .replace("+00:00", "Z"),
                "actor": "replay-runner",
                "action": stage,
                "narrative": f"Recorded {stage} stage from canonical replay fixture.",
                "input_references": [],
                "output_references": [],
                "evidence_references": [],
            }
        )
    return output


__all__ = [
    "CANONICAL_CASE_ID",
    "CANONICAL_TENANT_ID",
    "build_operator_view",
    "create_operator_view_router",
]
