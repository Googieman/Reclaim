"""Isolated Action Gateway request, execution, and verification contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from .analysis_policy import ActionType
from .common import ContractModel, require_utc


class ActionExecutionState(StrEnum):
    NOT_STARTED = "not_started"
    RECEIVED = "received"
    VALIDATED = "validated"
    PENDING_REMOTE = "pending_remote"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RECONCILING = "reconciling"
    RECONCILED = "reconciled"
    VERIFYING = "verifying"
    VERIFIED_SUCCESS = "verified_success"
    VERIFIED_FAILURE = "verified_failure"
    ESCALATED = "escalated"


class ActionGatewayRequest(ContractModel):
    case_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    action_type: ActionType
    connector_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    target_resource: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    policy_decision_id: str = Field(min_length=1)
    policy_version_id: str = Field(min_length=1)
    approval_id: str | None = None
    idempotency_key: str = Field(min_length=1)
    causation_id: str = Field(min_length=1)
    request_checksum: str = Field(min_length=1)
    requested_at: datetime

    _normalize_requested_at = field_validator("requested_at")(require_utc)


class ActionGatewayResponse(ContractModel):
    execution_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    state: ActionExecutionState
    connector_result: str = Field(min_length=1)
    remote_reference: str | None = None
    idempotency_key: str = Field(min_length=1)
    reconciliation_required: bool = False
    verification_required: bool = True
    audit_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def unknown_requires_reconciliation(self) -> ActionGatewayResponse:
        if self.state is ActionExecutionState.UNKNOWN:
            object.__setattr__(self, "reconciliation_required", True)
        return self


class VerificationRequest(ContractModel):
    execution_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    target_resource: str = Field(min_length=1)
    requested_at: datetime

    _normalize_requested_at = field_validator("requested_at")(require_utc)


class VerificationResult(StrEnum):
    VERIFIED_SUCCESS = "verified_success"
    VERIFIED_FAILURE = "verified_failure"
    INCONCLUSIVE = "inconclusive"


class VerificationResponse(ContractModel):
    verification_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    observed_resource_state: str = Field(min_length=1)
    verifier_source: str = Field(min_length=1)
    result: VerificationResult
    evidence_references: tuple[str, ...] = ()
    verified_at: datetime

    _normalize_verified_at = field_validator("verified_at")(require_utc)


ActionRequest = ActionGatewayRequest
ActionResponse = ActionGatewayResponse
