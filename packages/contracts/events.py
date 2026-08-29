"""Versioned event envelope and event-family identifiers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from .common import ContractModel, require_utc


class EventType(StrEnum):
    INCIDENT_ACCEPTED = "incident.accepted"
    WEBHOOK_QUARANTINED = "webhook.quarantined"
    EVIDENCE_COLLECTED = "evidence.collected"
    TIMELINE_REBUILT = "timeline.rebuilt"
    ATTRIBUTION_COMPLETED = "attribution.completed"
    EXPOSURE_CALCULATED = "exposure.calculated"
    PROPOSAL_CREATED = "proposal.created"
    POLICY_DECIDED = "policy.decided"
    APPROVAL_RECORDED = "approval.recorded"
    ACTION_REQUESTED = "action.requested"
    ACTION_UNKNOWN = "action.unknown"
    ACTION_RECONCILED = "action.reconciled"
    VERIFICATION_COMPLETED = "verification.completed"
    CASE_ESCALATED = "case.escalated"
    CASE_TERMINAL = "case.terminal"


class EventEnvelope(ContractModel):
    event_id: str = Field(min_length=1)
    event_type: EventType
    aggregate_type: str = Field(min_length=1)
    aggregate_id: str = Field(min_length=1)
    occurred_at: datetime
    produced_at: datetime
    causation_id: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    payload_checksum: str = Field(min_length=1)
    payload: dict[str, Any]

    _normalize_occurred_at = field_validator("occurred_at")(require_utc)
    _normalize_produced_at = field_validator("produced_at")(require_utc)

DomainEvent = EventEnvelope
