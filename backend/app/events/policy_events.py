"""Versioned policy and approval domain-event builders.

Builders only create envelopes.  Publication remains a separate outbox handoff
inside the PostgreSQL transaction that commits the authoritative record.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from packages.contracts.analysis_policy import Approval, PolicyDecision
from packages.contracts.events import EventEnvelope, EventType


def payload_checksum(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_policy_decided_event(
    decision: PolicyDecision,
    *,
    policy_checksum: str | None = None,
    producer: str = "deterministic-policy-evaluator@1.0.0",
) -> EventEnvelope:
    payload: dict[str, Any] = {
        "decision": decision.model_dump(mode="json"),
        "tenant_id": decision.tenant_id,
        "case_id": decision.case_id,
        "proposal_id": decision.proposal_id,
        "policy_version_id": decision.policy_version_id,
        "policy_checksum": policy_checksum or decision.evaluated_conditions.get("policy_checksum"),
        "result": decision.result.value,
        "evaluated_conditions": decision.evaluated_conditions,
    }
    occurred_at = decision.decided_at.astimezone(UTC)
    return EventEnvelope(
        tenant_id=decision.tenant_id,
        correlation_id=decision.correlation_id,
        event_id=f"policy.decided:{decision.decision_id}",
        event_type=EventType.POLICY_DECIDED,
        aggregate_type="case",
        aggregate_id=decision.case_id,
        occurred_at=occurred_at,
        produced_at=occurred_at,
        causation_id=decision.proposal_id,
        producer=producer,
        payload_checksum=payload_checksum(payload),
        payload=payload,
    )


def build_approval_recorded_event(
    approval: Approval,
    *,
    event_kind: str = "recorded",
    producer: str = "approval-service@1.0.0",
    occurred_at: datetime | None = None,
) -> EventEnvelope:
    if event_kind not in {"requested", "approved", "rejected", "expired", "revoked", "recorded"}:
        raise ValueError("approval event kind is unsupported")
    payload = {
        "approval": approval.model_dump(mode="json"),
        "tenant_id": approval.tenant_id,
        "case_id": approval.case_id,
        "proposal_id": approval.proposal_id,
        "policy_version_id": approval.policy_version_id,
        "approval_id": approval.approval_id,
        "actor": approval.approver_id,
        "status": approval.status.value,
        "provenance": {"separation_of_duties_evidence": approval.separation_of_duties_evidence},
    }
    when = (occurred_at or approval.approved_at).astimezone(UTC)
    return EventEnvelope(
        tenant_id=approval.tenant_id,
        correlation_id=approval.correlation_id,
        event_id=f"approval.recorded:{approval.approval_id}:{approval.status.value}",
        event_type=EventType.APPROVAL_RECORDED,
        aggregate_type="case",
        aggregate_id=approval.case_id,
        occurred_at=when,
        produced_at=when,
        causation_id=approval.proposal_id,
        producer=producer,
        payload_checksum=payload_checksum(payload),
        payload=payload,
    )


build_policy_event = build_policy_decided_event
build_policy_decision_event = build_policy_decided_event
build_approval_event = build_approval_recorded_event

__all__ = [
    "build_approval_recorded_event",
    "build_approval_event",
    "build_policy_decision_event",
    "build_policy_decided_event",
    "build_policy_event",
    "payload_checksum",
]
