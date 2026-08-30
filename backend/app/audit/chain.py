"""Checksum-linked append-only audit chain for authoritative events."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import hashlib
import json
from typing import Protocol

from packages.contracts.audit_replay import AuditRecord


class AuditRepository(Protocol):
    def latest_checksum(self, *, tenant_id: str) -> str | None: ...

    def append(self, record: AuditRecord) -> object: ...


class AuditChainError(ValueError):
    """Raised when audit linkage or checksum integrity is invalid."""


def checksum_for_record(record: AuditRecord) -> str:
    """Compute a stable digest over all audit fields except the digest itself."""

    payload = record.model_dump(mode="json")
    payload.pop("record_checksum", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AuditChain:
    """Build and append records linked to the latest tenant audit record."""

    def __init__(self, repository: AuditRepository) -> None:
        self.repository = repository

    def build_record(
        self,
        *,
        tenant_id: str,
        audit_id: str,
        case_id: str | None,
        actor: str,
        action: str,
        input_references: Sequence[str] = (),
        output_references: Sequence[str] = (),
        evidence_references: Sequence[str] = (),
        policy_version_id: str | None = None,
        model_version: str | None = None,
        provider_version: str | None = None,
        approval_id: str | None = None,
        execution_id: str | None = None,
        correlation_ids: Sequence[str] = (),
        outcome: str,
        recorded_at: datetime,
    ) -> AuditRecord:
        previous = self.repository.latest_checksum(tenant_id=tenant_id)
        candidate = AuditRecord(
            schema_version="1.0.0",
            tenant_id=tenant_id,
            correlation_id=correlation_ids[0] if correlation_ids else audit_id,
            audit_id=audit_id,
            case_id=case_id,
            actor=actor,
            action=action,
            input_references=tuple(input_references),
            output_references=tuple(output_references),
            evidence_references=tuple(evidence_references),
            policy_version_id=policy_version_id,
            model_version=model_version,
            provider_version=provider_version,
            approval_id=approval_id,
            execution_id=execution_id,
            correlation_ids=tuple(correlation_ids),
            outcome=outcome,
            recorded_at=recorded_at,
            previous_record_checksum=previous,
            record_checksum="pending",
        )
        return candidate.model_copy(update={"record_checksum": checksum_for_record(candidate)})

    def append(self, record: AuditRecord) -> AuditRecord:
        latest = self.repository.latest_checksum(tenant_id=record.tenant_id)
        if record.previous_record_checksum != latest:
            raise AuditChainError("audit record does not link to the latest tenant record")
        expected = checksum_for_record(record)
        if record.record_checksum != expected:
            raise AuditChainError("audit record checksum mismatch")
        self.repository.append(record)
        return record
