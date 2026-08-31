"""Append-only audit helpers for provider webhook intake."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from packages.contracts.audit_replay import AuditRecord
from packages.contracts.intake import VerifiedProviderCorrelation

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
    authoritative_mapping_id: str | None = None,
    verified_provider_correlation: VerifiedProviderCorrelation | None = None,
    assertion_status: str | None = None,
    asserted_incident_id: str | None = None,
    asserted_case_id: str | None = None,
) -> AuditRecord:
    """Record metadata and references, never raw payload bytes or secret values."""

    correlation_inputs = ()
    if verified_provider_correlation is not None:
        correlation_inputs = (
            f"correlation_schema:{verified_provider_correlation.correlation_schema_version}",
            f"provider:{verified_provider_correlation.provider}",
            f"provider_payment:{verified_provider_correlation.provider_payment_id}"
            if verified_provider_correlation.provider_payment_id
            else "provider_payment:absent",
            f"provider_order:{verified_provider_correlation.provider_order_id}"
            if verified_provider_correlation.provider_order_id
            else "provider_order:absent",
            f"verification:{verified_provider_correlation.verification.verifier_version}",
        )
    assertion_inputs = tuple(
        value
        for value in (
            f"mapping:{authoritative_mapping_id}" if authoritative_mapping_id else None,
            f"assertion_status:{assertion_status}" if assertion_status else None,
            f"asserted_incident:{asserted_incident_id}" if asserted_incident_id else None,
            f"asserted_case:{asserted_case_id}" if asserted_case_id else None,
        )
        if value
    )
    inputs = (
        tuple(value for value in (connector_id, provider_event_id, reason) if value)
        + correlation_inputs
        + assertion_inputs
    )
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
        provider_version="razorpay-test@2.0.0",
        correlation_ids=(correlation_id,),
        outcome=outcome,
        recorded_at=recorded_at,
    )
    return chain.append(record)
