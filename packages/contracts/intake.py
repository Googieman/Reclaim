"""Incident and Razorpay Test Mode intake contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
        if (
            not (self.report_content and self.report_content.strip())
            and not self.report_reference
        ):
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
        if (
            self.status in {IntakeStatus.ACCEPTED, IntakeStatus.DUPLICATE}
            and not self.incident_id
        ):
            raise ValueError("accepted and duplicate outcomes require incident_id")
        if self.status is IntakeStatus.ACCEPTED and not self.case_id:
            raise ValueError("accepted outcome requires case_id")
        if (
            self.status in {IntakeStatus.REJECTED, IntakeStatus.QUARANTINED}
            and not self.reason
        ):
            raise ValueError("rejected and quarantined outcomes require reason")
        return self


class VerifiedProviderVerification(BaseModel):
    """Proof metadata for a provider correlation derived after verification."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    state: Literal["verified"]
    method: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    payload_checksum: str = Field(min_length=1)
    verifier_version: str = Field(min_length=1)
    verified_at: datetime

    _normalize_verified_at = field_validator("verified_at")(require_utc)


class VerifiedProviderCorrelation(BaseModel):
    """Provider identity promoted only by a configured, successful verifier."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    correlation_schema_version: Literal["1.0.0"] = "1.0.0"
    provider: Literal["razorpay"]
    connector_id: str = Field(min_length=1)
    provider_event_id: str = Field(min_length=1)
    provider_payment_id: str | None = None
    provider_order_id: str | None = None
    merchant_reference: str | None = None
    verification: VerifiedProviderVerification

    @field_validator("provider_payment_id", "provider_order_id", "merchant_reference")
    @classmethod
    def normalize_optional_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider correlation identifiers cannot be blank")
        return normalized


class RazorpayWebhookRequest(ContractModel):
    """Original-payload webhook input; incomplete values remain representable for quarantine."""

    connector_id: str = Field(min_length=1)
    merchant_id: str | None = None
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
    authoritative_mapping_id: str | None = None
    association_status: str | None = None
    verified_provider_correlation: VerifiedProviderCorrelation | None = None
    reason: str | None = None
    audit_reference: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> WebhookProcessingResponse:
        if (
            self.status in {IntakeStatus.ACCEPTED, IntakeStatus.DUPLICATE}
            and not self.provider_event_id
        ):
            raise ValueError(
                "accepted and duplicate webhooks require provider_event_id"
            )
        if self.status in {IntakeStatus.ACCEPTED, IntakeStatus.DUPLICATE}:
            if self.verified_provider_correlation is None:
                raise ValueError(
                    "accepted and duplicate webhooks require verified provider correlation"
                )
            if not self.authoritative_mapping_id:
                raise ValueError(
                    "accepted and duplicate webhooks require authoritative_mapping_id"
                )
            if not self.incident_id or not self.case_id:
                raise ValueError(
                    "accepted and duplicate webhooks require mapped incident and case"
                )
            if self.association_status not in {None, "resolved"}:
                raise ValueError(
                    "accepted webhooks require resolved association status"
                )
        if (
            self.status in {IntakeStatus.REJECTED, IntakeStatus.QUARANTINED}
            and not self.reason
        ):
            raise ValueError("rejected and quarantined outcomes require reason")
        if self.status in {IntakeStatus.REJECTED, IntakeStatus.QUARANTINED} and (
            self.incident_id or self.case_id or self.authoritative_mapping_id
        ):
            raise ValueError(
                "quarantined webhooks cannot carry authoritative association"
            )
        return self


IntakeResponse = IncidentIntakeResponse
WebhookResponse = WebhookProcessingResponse
