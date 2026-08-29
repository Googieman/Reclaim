"""Append-only audit, replay, and evaluation metadata contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, require_utc


class AuditRecord(ContractModel):
    audit_id: str = Field(min_length=1)
    case_id: str | None = None
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    input_references: tuple[str, ...] = ()
    output_references: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()
    policy_version_id: str | None = None
    model_version: str | None = None
    provider_version: str | None = None
    approval_id: str | None = None
    execution_id: str | None = None
    correlation_ids: tuple[str, ...] = ()
    outcome: str = Field(min_length=1)
    recorded_at: datetime
    previous_record_checksum: str | None = None
    record_checksum: str = Field(min_length=1)

    _normalize_recorded_at = field_validator("recorded_at")(require_utc)



class RunMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"


class ReplayRun(ContractModel):
    run_id: str = Field(min_length=1)
    fixture_version: str = Field(min_length=1)
    connector_simulator_version: str = Field(min_length=1)
    action_simulator_version: str = Field(min_length=1)
    policy_version_id: str = Field(min_length=1)
    model_provider_mode: str = Field(min_length=1)
    deterministic_seed: int = Field(ge=0)
    environment_metadata: dict[str, Any]
    mode: RunMode
    stage_outcomes: dict[str, str]
    terminal_state: str | None = None
    differences_from_expected: tuple[str, ...] = ()
    label: str = "replay"

    @model_validator(mode="after")
    def enforce_replay_label(self) -> ReplayRun:
        if self.mode is RunMode.REPLAY and self.label != "replay":
            raise ValueError("replay runs must carry the replay label")
        return self


class EvaluationSplit(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    HELD_OUT = "held_out"


class EvaluationCase(ContractModel):
    evaluation_case_id: str = Field(min_length=1)
    provenance: dict[str, Any]
    label_source: str = Field(min_length=1)
    split: EvaluationSplit
    entity_group_id: str = Field(min_length=1)
    customer_group_id: str | None = None
    temporal_boundary: datetime
    synthetic_overlay_lineage: str | None = None
    class_labels: tuple[str, ...] = Field(min_length=1)
    no_compromise_false_alert: bool
    mixed_legitimate_malicious: bool
    expected_outcomes: dict[str, Any]
    observed_outcomes: dict[str, Any] = Field(default_factory=dict)
    leakage_checks: dict[str, bool]
    held_out_access_policy: str = Field(min_length=1)
    confidence_interval_metadata: dict[str, Any] = Field(default_factory=dict)
    metric_references: tuple[str, ...] = ()

    _normalize_temporal_boundary = field_validator("temporal_boundary")(require_utc)
