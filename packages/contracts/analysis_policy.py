"""Bounded model-analysis, typed-proposal, policy, and approval contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import ContractModel, require_utc


class ProviderMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"


class AttributionLabel(StrEnum):
    MALICIOUS = "malicious"
    LEGITIMATE = "legitimate"
    UNCERTAIN = "uncertain"


class ActionType(StrEnum):
    REVOKE_SUSPICIOUS_SESSION = "revoke_suspicious_session"
    HOLD_FULFILLMENT = "hold_fulfillment"
    CANCEL_ORDER = "cancel_order"
    REFUND_PAYMENT = "refund_payment"
    RESTORE_IDENTITY = "restore_identity"


class ModelBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tokens: int = Field(ge=1, le=100_000)
    max_tool_calls: int = Field(default=0, ge=0, le=100)
    timeout_seconds: int = Field(default=60, ge=1, le=900)


class ModelAnalysisRequest(ContractModel):
    case_id: str = Field(min_length=1)
    redacted_case_representation: dict[str, Any]
    evidence_references: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    policy_version_id: str = Field(min_length=1)
    budget: ModelBudget
    provider_mode: ProviderMode
    replay_label: ProviderMode

    @model_validator(mode="after")
    def forbid_action_capability(self) -> ModelAnalysisRequest:
        forbidden = {"execute_payment", "refund", "cancel", "database_write", "shell", "network"}
        requested = forbidden.intersection(self.allowed_tools)
        if requested:
            raise ValueError(f"forbidden model tools requested: {sorted(requested)}")
        return self


class AttributionSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeline_event_id: str = Field(min_length=1)
    label: AttributionLabel
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = ()
    method: str = Field(min_length=1)
    model_or_rules_version: str = Field(min_length=1)


class TypedActionProposal(ContractModel):
    proposal_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    action_type: ActionType
    target_resource: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = ()
    attribution_references: tuple[str, ...] = ()
    requested_amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    idempotency_key: str = Field(min_length=1)
    analysis_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_explicit_currency_for_amount(self) -> TypedActionProposal:
        if self.requested_amount_minor is not None and not self.currency:
            raise ValueError("requested amount requires explicit currency")
        if self.action_type is ActionType.REFUND_PAYMENT and self.requested_amount_minor is None:
            raise ValueError("refund proposal requires requested amount")
        return self


class ModelAnalysisResponse(ContractModel):
    analysis_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    attributions: tuple[AttributionSuggestion, ...] = ()
    proposals: tuple[TypedActionProposal, ...] = ()
    uncertainty: str = Field(min_length=1)
    refusal_records: tuple[str, ...] = ()
    token_count: int | None = Field(default=None, ge=0)
    estimated_cost: Decimal | None = Field(default=None, ge=0)


class PolicyResult(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"
    ESCALATE = "escalate"


class PolicyDecision(ContractModel):
    decision_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    policy_version_id: str = Field(min_length=1)
    result: PolicyResult
    evaluated_conditions: dict[str, Any]
    evaluator_version: str = Field(min_length=1)
    decided_at: datetime

    _normalize_decided_at = field_validator("decided_at")(require_utc)


class ApprovalStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Approval(ContractModel):
    approval_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    approver_id: str = Field(min_length=1)
    approver_role: str = Field(min_length=1)
    proposer_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    policy_version_id: str = Field(min_length=1)
    status: ApprovalStatus
    approved_at: datetime
    expires_at: datetime | None = None
    separation_of_duties_evidence: str = Field(min_length=1)

    _normalize_approved_at = field_validator("approved_at")(require_utc)
    _normalize_expires_at = field_validator("expires_at")(require_utc)

    @model_validator(mode="after")
    def enforce_separation_and_time(self) -> Approval:
        if self.approver_id == self.proposer_id:
            raise ValueError("approver and proposer must be distinct")
        if self.expires_at is not None and self.expires_at <= self.approved_at:
            raise ValueError("approval expiry must be after approval time")
        return self
