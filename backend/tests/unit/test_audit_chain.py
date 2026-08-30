"""Unit tests for the checksum-linked audit boundary."""

from datetime import datetime, timezone

import pytest

from app.audit.chain import AuditChain, AuditChainError, checksum_for_record
from packages.contracts.audit_replay import AuditRecord


class FakeAuditRepository:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def latest_checksum(self, *, tenant_id: str) -> str | None:
        for record in reversed(self.records):
            if record.tenant_id == tenant_id:
                return record.record_checksum
        return None

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


def make_chain() -> tuple[AuditChain, FakeAuditRepository]:
    repository = FakeAuditRepository()
    return AuditChain(repository), repository


def test_records_are_deterministically_linked_and_appended() -> None:
    chain, repository = make_chain()
    timestamp = datetime(2026, 8, 30, tzinfo=timezone.utc)

    first = chain.build_record(
        tenant_id="tenant-a",
        audit_id="audit-1",
        case_id="case-1",
        actor="intake-service",
        action="incident.accepted",
        correlation_ids=("corr-1",),
        outcome="accepted",
        recorded_at=timestamp,
    )
    assert first.previous_record_checksum is None
    assert first.record_checksum == checksum_for_record(first)
    chain.append(first)

    second = chain.build_record(
        tenant_id="tenant-a",
        audit_id="audit-2",
        case_id="case-1",
        actor="workflow-service",
        action="timeline.rebuilt",
        input_references=("evidence-1",),
        correlation_ids=("corr-1",),
        outcome="ready",
        recorded_at=timestamp,
    )
    assert second.previous_record_checksum == first.record_checksum
    chain.append(second)
    assert repository.records == [first, second]


def test_tampered_record_and_stale_link_are_rejected() -> None:
    chain, repository = make_chain()
    record = chain.build_record(
        tenant_id="tenant-a",
        audit_id="audit-1",
        case_id=None,
        actor="service",
        action="test",
        outcome="ok",
        recorded_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    tampered = record.model_copy(update={"outcome": "changed"})
    with pytest.raises(AuditChainError, match="checksum"):
        chain.append(tampered)

    chain.append(record)
    stale = chain.build_record(
        tenant_id="tenant-a",
        audit_id="audit-2",
        case_id=None,
        actor="service",
        action="test-2",
        outcome="ok",
        recorded_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    repository.records.append(
        chain.build_record(
            tenant_id="tenant-a",
            audit_id="audit-3",
            case_id=None,
            actor="service",
            action="test-3",
            outcome="ok",
            recorded_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        )
    )
    with pytest.raises(AuditChainError, match="latest"):
        chain.append(stale)
