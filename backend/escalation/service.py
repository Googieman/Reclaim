"""Authoritative tenant-scoped escalation service."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.auth.oidc import RequiredRole, TenantAuthorizationContext


class EscalationError(ValueError):
    """Raised when unresolved work cannot be safely assigned or recorded."""


SUPPORTED_RECOMMENDATIONS = frozenset(
    {
        "reconcile merchant state and decide containment",
        "review merchant state and decide containment",
        "manual review required",
    }
)


@dataclass(frozen=True, slots=True)
class EscalationRecord:
    tenant_id: str
    escalation_id: str
    case_id: str
    owner_id: str
    reason: str
    remaining_exposure_minor: int
    currency: str
    evidence_references: tuple[str, ...]
    recommended_human_decision: str
    state: str = "open"
    canonical_action_id: str | None = None
    execution_id: str | None = None
    verification_id: str | None = None
    policy_version_id: str | None = None
    action_version: str = "action-idempotency-v1.0.0"
    verification_version: str | None = None
    checksum: str = ""
    created_at: datetime | None = None
    correlation_id: str | None = None

    @property
    def owner(self) -> str:
        return self.owner_id

    def __post_init__(self) -> None:
        for name in ("tenant_id", "escalation_id", "case_id", "owner_id", "reason"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise EscalationError(f"{name} is required")
        if isinstance(self.remaining_exposure_minor, bool) or self.remaining_exposure_minor < 0:
            raise EscalationError("remaining exposure must be a non-negative integer")
        if (
            not isinstance(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isalpha()
        ):
            raise EscalationError("explicit ISO currency is required")
        if self.state not in {"open", "resolved"}:
            raise EscalationError("escalation state is unsupported")
        if not self.evidence_references:
            raise EscalationError("authoritative evidence references are required")
        if not self.recommended_human_decision.strip():
            raise EscalationError("recommended human decision is required")
        if self.created_at is not None and (
            self.created_at.tzinfo is None or self.created_at.utcoffset() is None
        ):
            raise EscalationError("escalation timestamp must include timezone")
        if self.checksum and len(self.checksum) != 64:
            raise EscalationError("escalation checksum is malformed")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise EscalationError("escalation correlation identity is malformed")


class EscalationService:
    """Create escalation authority only for a tenant-scoped human owner."""

    def __init__(self, *, repository: Any | None = None) -> None:
        self.repository = repository

    def create(
        self,
        *,
        tenant_id: str,
        case_id: str,
        owner_id: str,
        reason: str,
        remaining_exposure_minor: int,
        currency: str,
        evidence_references: Sequence[str],
        recommended_human_decision: str,
        owner_tenant_id: str | None = None,
        authorization_context: TenantAuthorizationContext | None = None,
        escalation_id: str | None = None,
        canonical_action_id: str | None = None,
        execution_id: str | None = None,
        verification_id: str | None = None,
        policy_version_id: str | None = None,
        action_version: str = "action-idempotency-v1.0.0",
        verification_version: str | None = None,
        correlation_id: str | None = None,
        authoritative_exposure: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> EscalationRecord:
        owner_tenant = owner_tenant_id or (
            authorization_context.tenant_id if authorization_context is not None else None
        )
        _require_owner(
            tenant_id=tenant_id,
            owner_id=owner_id,
            owner_tenant_id=owner_tenant,
            authorization_context=authorization_context,
        )
        _require_financial_identity(currency, remaining_exposure_minor)
        evidence = _references(evidence_references)
        if not evidence:
            raise EscalationError("authoritative evidence references are required")
        if authoritative_exposure is not None:
            if authoritative_exposure.get("tenant_id") not in {None, tenant_id}:
                raise EscalationError("exposure crosses tenant scope")
            if authoritative_exposure.get("case_id") not in {None, case_id}:
                raise EscalationError("exposure crosses case scope")
            authoritative_amount = authoritative_exposure.get("remaining_exposure_minor")
            authoritative_currency = authoritative_exposure.get("currency")
            if (
                authoritative_amount != remaining_exposure_minor
                or str(authoritative_currency).upper() != currency.upper()
            ):
                raise EscalationError("remaining exposure is not the authoritative value")
        if recommended_human_decision not in SUPPORTED_RECOMMENDATIONS:
            raise EscalationError("recommended human decision is unsupported")
        when = _utc(created_at or datetime.now(UTC))
        escalation = EscalationRecord(
            tenant_id=tenant_id,
            escalation_id=escalation_id
            or _escalation_id(tenant_id, case_id, execution_id, verification_id, reason),
            case_id=case_id,
            owner_id=owner_id,
            reason=reason.strip(),
            remaining_exposure_minor=remaining_exposure_minor,
            currency=currency.upper(),
            evidence_references=evidence,
            recommended_human_decision=recommended_human_decision,
            canonical_action_id=canonical_action_id,
            execution_id=execution_id,
            verification_id=verification_id,
            policy_version_id=policy_version_id,
            action_version=action_version,
            verification_version=verification_version,
            created_at=when,
            correlation_id=correlation_id,
        )
        object.__setattr__(
            escalation,
            "checksum",
            _checksum(escalation),
        )
        if self.repository is not None:
            self.repository.create(
                escalation_id=escalation.escalation_id,
                case_id=escalation.case_id,
                owner=escalation.owner_id,
                owner_tenant_id=tenant_id,
                reason=escalation.reason,
                remaining_exposure_minor=escalation.remaining_exposure_minor,
                currency=escalation.currency,
                evidence_references=escalation.evidence_references,
                recommended_human_decision=escalation.recommended_human_decision,
                canonical_action_id=escalation.canonical_action_id,
                execution_id=escalation.execution_id,
                verification_id=escalation.verification_id,
                policy_version_id=escalation.policy_version_id,
                action_version=escalation.action_version,
                verification_version=escalation.verification_version,
                correlation_id=escalation.correlation_id,
                checksum=escalation.checksum,
                state=escalation.state,
                created_at=escalation.created_at,
            )
        return escalation

    escalate = create


def _require_owner(
    *,
    tenant_id: str,
    owner_id: str,
    owner_tenant_id: str | None,
    authorization_context: TenantAuthorizationContext | None,
) -> None:
    if owner_tenant_id != tenant_id:
        raise EscalationError("escalation owner crosses tenant scope")
    if authorization_context is not None:
        if authorization_context.tenant_id != tenant_id:
            raise EscalationError("escalation authorization crosses tenant scope")
        try:
            authorization_context.require_role(RequiredRole.ESCALATION_OWNER)
        except PermissionError as exc:
            raise EscalationError("authenticated escalation-owner role is required") from exc
        if authorization_context.subject != owner_id:
            raise EscalationError("escalation owner must be the authenticated principal")


def _require_financial_identity(currency: str, amount: int) -> None:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise EscalationError("remaining exposure must be a non-negative integer")
    if (
        not isinstance(currency, str)
        or len(currency.strip()) != 3
        or not currency.strip().isalpha()
    ):
        raise EscalationError("explicit ISO currency is required")


def _references(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in values)
    if any(not value for value in normalized):
        raise EscalationError("evidence references cannot be blank")
    return tuple(dict.fromkeys(normalized))


def _escalation_id(*values: str | None) -> str:
    return (
        "escalation:"
        + hashlib.sha256(": ".join(value or "" for value in values).encode()).hexdigest()
    )


def _checksum(record: EscalationRecord) -> str:
    data = {
        "tenant_id": record.tenant_id,
        "escalation_id": record.escalation_id,
        "case_id": record.case_id,
        "owner_id": record.owner_id,
        "reason": record.reason,
        "remaining_exposure_minor": record.remaining_exposure_minor,
        "currency": record.currency,
        "evidence_references": record.evidence_references,
        "recommended_human_decision": record.recommended_human_decision,
        "canonical_action_id": record.canonical_action_id,
        "execution_id": record.execution_id,
        "verification_id": record.verification_id,
        "policy_version_id": record.policy_version_id,
        "action_version": record.action_version,
        "verification_version": record.verification_version,
        "correlation_id": record.correlation_id,
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EscalationError("escalation timestamp must include timezone")
    return value.astimezone(UTC)


__all__ = ["EscalationError", "EscalationRecord", "EscalationService", "SUPPORTED_RECOMMENDATIONS"]
