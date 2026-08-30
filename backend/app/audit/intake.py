"""Append-only audit helpers for provider webhook intake."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from packages.contracts.audit_replay import AuditRecord

from app.audit.chain import AuditChain
from app.db.unit_of_work import PostgresUnitOfWork


def append_webhook_audit(
    *,
    unit_of_work: PostgresUnitOfWork,
    audit_id: str,
    tenant_id: str,
    correlation_id: str,
    actor: str,
    outcome: str,
    recorded_at: datetime,
    raw_object_reference: str,
    provider_event_id: str | None,
    connector_id: str,
    case_id: str | None = None,
    output_references: Sequence[str] = (),
    reason: str | None = None,
) -> AuditRecord:
    """Record metadata and references, never raw payload bytes or secret values."""

    inputs = tuple(value for value in (connector_id, provider_event_id, reason) if value)
    outputs = tuple(output_references)
    chain = AuditChain(unit_of_work.audit)
    record = chain.build_record(
        tenant_id=tenant_id,
        audit_id=audit_id,
        case_id=case_id,
        actor=actor,
        action="webhook.intake",
        input_references=inputs,
        output_references=outputs,
        evidence_references=(raw_object_reference,),
        provider_version="razorpay-test@1.0.0",
        correlation_ids=(correlation_id,),
        outcome=outcome,
        recorded_at=recorded_at,
    )
    return chain.append(record)
