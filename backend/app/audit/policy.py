"""Append-only audit and outbox handoff for policy/approval outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from packages.contracts.analysis_policy import Approval, PolicyDecision
from packages.contracts.audit_replay import AuditRecord

from app.audit.chain import AuditChain, checksum_for_record
from app.events.policy_events import (
    build_approval_recorded_event,
    build_policy_decided_event,
)


@dataclass(frozen=True, slots=True)
class PolicyPersistenceResult:
    decision: PolicyDecision | None
    approval: Approval | None
    audit_record: AuditRecord
    event: object
    persisted: bool


def persist_policy_decision(
    decision: PolicyDecision,
    *,
    unit_of_work: Any | None = None,
    actor: str = "deterministic-policy-evaluator",
    audit_id: str | None = None,
    policy_checksum: str | None = None,
    recorded_at: datetime | None = None,
) -> PolicyPersistenceResult:
    """Persist a decision and enqueue its event in one supplied transaction."""

    if not isinstance(decision, PolicyDecision):
        raise TypeError("policy decision must be a PolicyDecision")
    when = _utc(recorded_at or decision.decided_at)
    policy_checksum = policy_checksum or decision.evaluated_conditions.get("policy_checksum")
    if unit_of_work is not None:
        _persist_decision_row(unit_of_work, decision)
    audit = _audit_record_for_decision(
        decision,
        actor=actor,
        audit_id=audit_id,
        recorded_at=when,
    )
    if unit_of_work is not None:
        chain = AuditChain(unit_of_work.audit)
        audit = chain.append(audit)
    event = build_policy_decided_event(decision, policy_checksum=policy_checksum)
    if unit_of_work is not None:
        unit_of_work.outbox.enqueue(outbox_id=f"outbox:{event.event_id}", event=event)
    return PolicyPersistenceResult(decision, None, audit, event, unit_of_work is not None)


def persist_approval_event(
    approval: Approval,
    *,
    unit_of_work: Any | None = None,
    actor: str | None = None,
    audit_id: str | None = None,
    event_kind: str = "recorded",
    recorded_at: datetime | None = None,
) -> PolicyPersistenceResult:
    """Persist one approval lifecycle value and enqueue its versioned event."""

    if not isinstance(approval, Approval):
        raise TypeError("approval must be an Approval")
    when = _utc(recorded_at or approval.approved_at)
    if unit_of_work is not None:
        _persist_approval_row(unit_of_work, approval)
    audit = _audit_record_for_approval(
        approval,
        actor=actor or approval.approver_id,
        audit_id=audit_id,
        recorded_at=when,
    )
    if unit_of_work is not None:
        chain = AuditChain(unit_of_work.audit)
        audit = chain.append(audit)
    event = build_approval_recorded_event(approval, event_kind=event_kind, occurred_at=when)
    if unit_of_work is not None:
        unit_of_work.outbox.enqueue(outbox_id=f"outbox:{event.event_id}", event=event)
    return PolicyPersistenceResult(None, approval, audit, event, unit_of_work is not None)


def _persist_decision_row(unit_of_work: Any, decision: PolicyDecision) -> None:
    conditions = decision.evaluated_conditions
    scope_type = str(conditions.get("policy_scope_type", "tenant"))
    unit_of_work.policy_decisions.create(
        decision_id=decision.decision_id,
        case_id=decision.case_id,
        proposal_id=decision.proposal_id,
        policy_version_id=decision.policy_version_id,
        result=decision.result.value,
        evaluated_conditions=conditions,
        evaluator_version=decision.evaluator_version,
        decided_at=decision.decided_at,
        policy_scope_type=scope_type,
    )


def _persist_approval_row(unit_of_work: Any, approval: Approval) -> None:
    repository = unit_of_work.approvals
    existing = None
    get = getattr(repository, "get", None)
    if callable(get):
        existing = get(approval_id=approval.approval_id)
    if existing is not None:
        update_status = getattr(repository, "update_status", None)
        if not callable(update_status):
            raise RuntimeError("approval lifecycle repository cannot update an existing record")
        update_status(
            approval_id=approval.approval_id,
            status=approval.status.value,
            expected_version=_row_version(existing),
        )
        return
    create_kwargs = {
        "approval_id": approval.approval_id,
        "case_id": approval.case_id,
        "proposal_id": approval.proposal_id,
        "approver_id": approval.approver_id,
        "approver_role": approval.approver_role,
        "proposer_id": approval.proposer_id,
        "scope": approval.scope,
        "policy_version_id": approval.policy_version_id,
        "status": approval.status.value,
        "approved_at": approval.approved_at,
        "expires_at": approval.expires_at,
        "separation_of_duties_evidence": approval.separation_of_duties_evidence,
    }
    if "correlation_id" in getattr(repository.create, "__annotations__", {}):
        create_kwargs["correlation_id"] = approval.correlation_id
    repository.create(**create_kwargs)


def _row_version(row: object) -> int:
    if isinstance(row, Mapping):
        value = row.get("version")
    else:
        value = row[13] if len(row) > 13 else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError("approval version is missing from the authoritative row")
    return value


def _audit_record_for_decision(
    decision: PolicyDecision,
    *,
    actor: str,
    audit_id: str | None,
    recorded_at: datetime,
) -> AuditRecord:
    return _standalone_audit(
        tenant_id=decision.tenant_id,
        case_id=decision.case_id,
        correlation_id=decision.correlation_id,
        audit_id=audit_id or f"audit:policy:{decision.decision_id}",
        actor=actor,
        action="policy.decision",
        input_references=(decision.proposal_id, decision.policy_version_id),
        output_references=(decision.decision_id,),
        policy_version_id=decision.policy_version_id,
        outcome=decision.result.value,
        recorded_at=recorded_at,
    )


def _audit_record_for_approval(
    approval: Approval,
    *,
    actor: str,
    audit_id: str | None,
    recorded_at: datetime,
) -> AuditRecord:
    return _standalone_audit(
        tenant_id=approval.tenant_id,
        case_id=approval.case_id,
        correlation_id=approval.correlation_id,
        audit_id=audit_id or f"audit:approval:{approval.approval_id}:{approval.status.value}",
        actor=actor,
        action="approval.lifecycle",
        input_references=(approval.proposal_id, approval.policy_version_id),
        output_references=(approval.approval_id,),
        policy_version_id=approval.policy_version_id,
        approval_id=approval.approval_id,
        outcome=approval.status.value,
        recorded_at=recorded_at,
    )


def _standalone_audit(
    *,
    tenant_id: str,
    case_id: str,
    correlation_id: str,
    audit_id: str,
    actor: str,
    action: str,
    input_references: tuple[str, ...],
    output_references: tuple[str, ...],
    policy_version_id: str,
    outcome: str,
    recorded_at: datetime,
    approval_id: str | None = None,
) -> AuditRecord:
    candidate = AuditRecord(
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        audit_id=audit_id,
        case_id=case_id,
        actor=actor,
        action=action,
        input_references=input_references,
        output_references=output_references,
        policy_version_id=policy_version_id,
        approval_id=approval_id,
        outcome=outcome,
        recorded_at=recorded_at,
        record_checksum="pending",
    )
    return candidate.model_copy(update={"record_checksum": checksum_for_record(candidate)})


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("policy audit timestamp must include a timezone")
    return value.astimezone(UTC)


__all__ = ["PolicyPersistenceResult", "persist_approval_event", "persist_policy_decision"]
