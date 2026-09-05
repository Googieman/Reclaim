"""Checksum-linked audit records for the Action Gateway lifecycle."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from packages.contracts.audit_replay import AuditRecord

from app.audit.chain import AuditChain


@dataclass(frozen=True, slots=True)
class ActionAuditResult:
    audit_record: AuditRecord
    event: object | None
    persisted: bool


def persist_action_audit(
    *,
    tenant_id: str,
    case_id: str,
    outcome: str,
    action_id: str | None = None,
    execution_id: str | None = None,
    verification_id: str | None = None,
    escalation_id: str | None = None,
    policy_version_id: str | None = None,
    approval_id: str | None = None,
    evidence_references: Sequence[str] = (),
    correlation_ids: Sequence[str] = (),
    actor: str = "action-gateway",
    unit_of_work: Any | None = None,
    audit_id: str | None = None,
    recorded_at: datetime | None = None,
) -> ActionAuditResult:
    """Append an action outcome and optionally enqueue its event transactionally."""

    when = _utc(recorded_at or datetime.now(UTC))
    output_references = tuple(
        reference
        for reference in (action_id, execution_id, verification_id, escalation_id)
        if reference
    )
    input_references = tuple(
        reference for reference in (policy_version_id, approval_id) if reference
    )
    if unit_of_work is not None:
        chain = AuditChain(unit_of_work.audit)
        audit = chain.build_record(
            tenant_id=tenant_id,
            audit_id=audit_id or f"audit:action:{execution_id or action_id or case_id}:{outcome}",
            case_id=case_id,
            actor=actor,
            action="action.lifecycle",
            input_references=input_references,
            output_references=output_references,
            evidence_references=evidence_references,
            policy_version_id=policy_version_id,
            approval_id=approval_id,
            execution_id=execution_id,
            correlation_ids=correlation_ids,
            outcome=outcome,
            recorded_at=when,
        )
        audit = chain.append(audit)
    else:
        audit = AuditRecord(
            tenant_id=tenant_id,
            correlation_id=correlation_ids[0] if correlation_ids else case_id,
            audit_id=audit_id or f"audit:action:{execution_id or action_id or case_id}:{outcome}",
            case_id=case_id,
            actor=actor,
            action="action.lifecycle",
            input_references=input_references,
            output_references=output_references,
            evidence_references=tuple(evidence_references),
            policy_version_id=policy_version_id,
            approval_id=approval_id,
            execution_id=execution_id,
            correlation_ids=tuple(correlation_ids),
            outcome=outcome,
            recorded_at=when,
            record_checksum="pending",
        )
        from app.audit.chain import checksum_for_record

        audit = audit.model_copy(update={"record_checksum": checksum_for_record(audit)})
    return ActionAuditResult(audit, None, unit_of_work is not None)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("action audit timestamp must include timezone")
    return value.astimezone(UTC)


__all__ = ["ActionAuditResult", "persist_action_audit"]
