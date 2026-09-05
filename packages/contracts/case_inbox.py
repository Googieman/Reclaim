"""Tenant-scoped contracts for the operator case inbox."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import ContractModel, require_utc


class OrchestrationStage(StrEnum):
    NORMALIZE_INTAKE = "normalize_intake"
    ANALYZE = "analyze"
    HUMAN_HANDOFF = "human_handoff"


class OrchestrationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_HUMAN = "awaiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    REQUIRES_ATTENTION = "requires_attention"


class OrchestrationSummary(BaseModel):
    """The latest authoritative n8n handoff state for a case."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    run_id: str = Field(min_length=1)
    workflow_version: str = Field(min_length=1)
    external_execution_id: str = Field(min_length=1)
    stage: OrchestrationStage
    status: OrchestrationStatus
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime
    failure_code: str | None = None

    _normalize_queued_at = field_validator("queued_at")(require_utc)
    _normalize_started_at = field_validator("started_at")(require_utc)
    _normalize_completed_at = field_validator("completed_at")(require_utc)
    _normalize_updated_at = field_validator("updated_at")(require_utc)


class CaseInboxItem(BaseModel):
    """Searchable, narrative-free case row returned to the operator inbox."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    merchant_name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    incident_type: str = Field(min_length=1)
    occurred_at: datetime
    state: str = Field(min_length=1)
    updated_at: datetime
    created_at: datetime
    identifiers: dict[str, str] = Field(default_factory=dict)
    reported_amount_minor: int | None = Field(default=None, ge=0)
    reported_currency: str | None = Field(default=None, min_length=3, max_length=3)
    external_reference: str | None = None
    orchestration: OrchestrationSummary | None = None

    _normalize_occurred_at = field_validator("occurred_at")(require_utc)
    _normalize_updated_at = field_validator("updated_at")(require_utc)
    _normalize_created_at = field_validator("created_at")(require_utc)


class CaseInboxPage(ContractModel):
    """Cursor-paginated case inbox page."""

    items: list[CaseInboxItem] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False
    limit: int = Field(ge=1, le=100)


__all__ = [
    "CaseInboxItem",
    "CaseInboxPage",
    "OrchestrationStage",
    "OrchestrationStatus",
    "OrchestrationSummary",
]
