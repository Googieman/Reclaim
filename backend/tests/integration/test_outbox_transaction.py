"""Transactional outbox persistence and identity tests."""

from __future__ import annotations

import pytest

from app.db.unit_of_work import PostgresUnitOfWork
from app.events.outbox import OutboxConflictError

from .support import RecordingDatabase, make_event


def test_business_write_and_outbox_are_rolled_back_together() -> None:
    database = RecordingDatabase()
    with pytest.raises(RuntimeError, match="abort"):
        with PostgresUnitOfWork(database.connect, tenant_id="tenant-a") as unit_of_work:
            unit_of_work.incidents.create(
                incident_id="incident-1",
                source="operator",
                reporter_context={},
                received_at=make_event().occurred_at,
                correlation_key="corr-1",
                raw_input_reference=None,
                intake_status="accepted",
                deduplication_identity="intake-1",
            )
            unit_of_work.outbox.enqueue(outbox_id="outbox-1", event=make_event())
            raise RuntimeError("abort")

    assert database.business_rows == 0
    assert database.outbox == {}


def test_business_write_and_outbox_commit_on_the_same_unit_of_work() -> None:
    database = RecordingDatabase()
    with PostgresUnitOfWork(database.connect, tenant_id="tenant-a") as unit_of_work:
        unit_of_work.incidents.create(
            incident_id="incident-1",
            source="operator",
            reporter_context={},
            received_at=make_event().occurred_at,
            correlation_key="corr-1",
            raw_input_reference=None,
            intake_status="accepted",
            deduplication_identity="intake-1",
        )
        result = unit_of_work.outbox.enqueue(outbox_id="outbox-1", event=make_event())

    assert result.inserted
    assert database.business_rows == 1
    assert len(database.outbox) == 1


def test_duplicate_event_identity_returns_existing_outbox_without_second_row() -> None:
    database = RecordingDatabase()
    event = make_event()
    with PostgresUnitOfWork(database.connect, tenant_id="tenant-a") as unit_of_work:
        first = unit_of_work.outbox.enqueue(outbox_id="outbox-1", event=event)
        duplicate = unit_of_work.outbox.enqueue(outbox_id="outbox-2", event=event)

    assert first.inserted
    assert not duplicate.inserted
    assert duplicate.outbox_id == "outbox-1"
    assert len(database.outbox) == 1


def test_duplicate_event_identity_with_different_content_is_rejected() -> None:
    database = RecordingDatabase()
    with PostgresUnitOfWork(database.connect, tenant_id="tenant-a") as unit_of_work:
        unit_of_work.outbox.enqueue(outbox_id="outbox-1", event=make_event())

    with pytest.raises(OutboxConflictError, match="different content"):
        with PostgresUnitOfWork(database.connect, tenant_id="tenant-a") as unit_of_work:
            unit_of_work.outbox.enqueue(
                outbox_id="outbox-2",
                event=make_event(payload_checksum="sha256:payload-2", payload={"source": "other"}),
            )
