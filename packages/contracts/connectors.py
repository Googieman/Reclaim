"""Versioned connector manifests and evidence/action exchange contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import ContractModel, require_utc


class ConnectorType(StrEnum):
    EVIDENCE = "evidence"
    ACTION = "action"


class ConnectorMode(StrEnum):
    LIVE = "live"
    SIMULATOR = "simulator"


class ConnectorFailureState(StrEnum):
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"
    STALE = "stale"
    INVALID = "invalid"
    TIMEOUT = "timeout"
    UNKNOWN_RESULT = "unknown_result"


class ConnectorLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_page_size: int = Field(default=100, ge=1, le=10_000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_payload_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)


class ConnectorManifest(ContractModel):
    """Tenant-scoped declaration of connector authority and failure behavior."""

    connector_id: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    connector_type: ConnectorType
    mode: ConnectorMode
    resources: tuple[str, ...] = Field(min_length=1)
    operations: tuple[str, ...] = Field(min_length=1)
    auth_scope: tuple[str, ...] = Field(min_length=1)
    request_schema: str = Field(min_length=1)
    response_schema: str = Field(min_length=1)
    limits: ConnectorLimits = Field(default_factory=ConnectorLimits)
    timestamp_semantics: str = Field(min_length=1)
    idempotency_behavior: str = Field(min_length=1)
    failure_states: tuple[ConnectorFailureState, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_declarations(self) -> ConnectorManifest:
        if len(set(self.resources)) != len(self.resources):
            raise ValueError("connector resources must be unique")
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("connector operations must be unique")
        return self


class EvidenceRequest(ContractModel):
    case_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    operation: str = "read"
    resource_ids: tuple[str, ...] = ()
    requested_at: datetime
    page_size: int = Field(default=100, ge=1, le=10_000)
    cursor: str | None = None

    _normalize_requested_at = field_validator("requested_at")(require_utc)


class EvidenceResponse(ContractModel):
    case_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    observed_at: datetime
    collected_at: datetime
    completeness: str = Field(pattern="^(complete|partial)$")
    raw_artifact_reference: str | None = None
    raw_checksum: str | None = None
    normalized_facts: list[dict[str, Any]] = Field(default_factory=list)
    connector_status: str = Field(min_length=1)
    failure_state: ConnectorFailureState | None = None
    untrusted: bool = True

    _normalize_observed_at = field_validator("observed_at")(require_utc)
    _normalize_collected_at = field_validator("collected_at")(require_utc)

    @model_validator(mode="after")
    def apply_partial_state(self) -> EvidenceResponse:
        if self.completeness == "partial" and self.failure_state is None:
            object.__setattr__(self, "failure_state", ConnectorFailureState.PARTIAL)
        return self


class ActionConnectorRequest(ContractModel):
    case_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    target_resource: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)
    requested_at: datetime

    _normalize_requested_at = field_validator("requested_at")(require_utc)


class ActionConnectorResult(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ActionConnectorResponse(ContractModel):
    case_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    result: ActionConnectorResult
    remote_reference: str | None = None
    idempotency_key: str = Field(min_length=1)
    attempt_count: int = Field(default=1, ge=1)
    reconciliation_required: bool = False
    failure_state: ConnectorFailureState | None = None
    completed_at: datetime | None = None

    _normalize_completed_at = field_validator("completed_at")(require_utc)

    @model_validator(mode="after")
    def validate_unknown_result(self) -> ActionConnectorResponse:
        if self.result is ActionConnectorResult.UNKNOWN:
            object.__setattr__(self, "reconciliation_required", True)
            if self.failure_state is None:
                object.__setattr__(self, "failure_state", ConnectorFailureState.UNKNOWN_RESULT)
        return self


ConnectorActionRequest = ActionConnectorRequest
ConnectorActionResponse = ActionConnectorResponse
