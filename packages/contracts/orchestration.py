"""Strict API contracts for the n8n durable orchestration boundary."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .case_inbox import OrchestrationStage, OrchestrationStatus


class OrchestrationOutcome(StrEnum):
    COMPLETED = "completed"
    AWAITING_HUMAN = "awaiting_human"
    FAILED = "failed"
    REQUIRES_ATTENTION = "requires_attention"


class StartOrchestrationRunRequest(BaseModel):
    """Body for creating one idempotent n8n handoff."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idempotency_key: str = Field(min_length=1, max_length=256)
    expected_state: str = Field(default="intake_received", min_length=1)
    external_execution_id: str = Field(min_length=1, max_length=256)
    workflow_version: str = Field(default="incident-analysis-handoff.v1", min_length=1)


class OrchestrationStageRequest(BaseModel):
    """Body for one allowlisted, expected-state-checked stage transition."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_state: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=256)
    outcome: OrchestrationOutcome = OrchestrationOutcome.COMPLETED
    failure_code: str | None = Field(default=None, max_length=80)


class OrchestrationRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    workflow_version: str = Field(min_length=1)
    external_execution_id: str = Field(min_length=1)
    stage: OrchestrationStage
    status: OrchestrationStatus
    failure_code: str | None = None


class NormalizedIntakeResponse(BaseModel):
    """Redacted structured intake projection returned to n8n."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: str = Field(pattern="^(normalized|empty_timeline|requires_attention)$")
    incident_type: str = Field(min_length=1)
    occurred_at: str = Field(min_length=1)
    report_reference: str | None = None
    narrative_checksum: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)


class OrchestrationRecoveryRequest(BaseModel):
    """Strict n8n error-workflow payload."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    run_id: str = Field(min_length=1, max_length=256)
    external_execution_id: str = Field(min_length=1, max_length=256)
    expected_state: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=256)
    failure_code: str = Field(min_length=1, max_length=80)


__all__ = [
    "OrchestrationOutcome",
    "OrchestrationRunResponse",
    "OrchestrationStageRequest",
    "NormalizedIntakeResponse",
    "OrchestrationRecoveryRequest",
    "StartOrchestrationRunRequest",
]
