"""Incident and Razorpay Test Mode intake contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, require_utc


class IntakeStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class IncidentIntakeRequest(ContractModel):
    """Authenticated merchant/operator account-compromise report."""

    source: str = Field(min_length=1)
    received_at: datetime
    reporter_context: dict[str, Any] = Field(default_factory=dict)
    report_content: str | None = None
    report_reference: str | None = None
    idempotency_key: str = Field(min_length=1)

    _normalize_received_at = field_validator("received_at")(require_utc)

    @model_validator(mode="after")
    def require_report_input(self) -> IncidentIntakeRequest:
        if not (self.report_content and self.report_content.strip()) and not self.report_reference:
            raise ValueError("report_content or report_reference is required")
        return self


class IncidentIntakeResponse(ContractModel):
    """Outcome of incident intake, including safe duplicate/quarantine states."""

    status: IntakeStatus
    incident_id: str | None = None
    case_id: str | None = None
    reason: str | None = None
    audit_reference: str | None = None

    @model_validator(mode="after")
    def validate_identity_for_status(self) -> IncidentIntakeResponse:
        if self.status in {IntakeStatus.ACCEPTED, IntakeStatus.DUPLICATE} and not self.incident_id:
            raise ValueError("accepted and duplicate outcomes require incident_id")
        if self.status is IntakeStatus.ACCEPTED and not self.case_id:
            raise ValueError("accepted outcome requires case_id")
        if self.status in {IntakeStatus.REJECTED, IntakeStatus.QUARANTINED} and not self.reason:
            raise ValueError("rejected and quarantined outcomes require reason")
        return self


class RazorpayWebhookRequest(ContractModel):
    """Original-payload webhook input; incomplete values remain representable for quarantine."""

    connector_id: str = Field(min_length=1)
    original_payload: bytes = Field(min_length=1)
    payload_checksum: str = Field(min_length=1)
    signature: str | None = None
    provider_event_id: str | None = None
    event_type: str | None = None
    event_timestamp: datetime | None = None
    received_at: datetime

    _normalize_received_at = field_validator("received_at")(require_utc)
    _normalize_event_timestamp = field_validator("event_timestamp")(require_utc)


class WebhookProcessingResponse(ContractModel):
    """Provider webhook outcome before downstream case processing."""

    status: IntakeStatus
    connector_id: str
    provider_event_id: str | None = None
    incident_id: str | None = None
    case_id: str | None = None
    reason: str | None = None
    audit_reference: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> WebhookProcessingResponse:
        if self.status in {IntakeStatus.ACCEPTED, IntakeStatus.DUPLICATE} and not self.provider_event_id:
            raise ValueError("accepted and duplicate webhooks require provider_event_id")
        if self.status in {IntakeStatus.REJECTED, IntakeStatus.QUARANTINED} and not self.reason:
            raise ValueError("rejected and quarantined webhooks require reason")
        return self


IntakeResponse = IncidentIntakeResponse
WebhookResponse = WebhookProcessingResponse
