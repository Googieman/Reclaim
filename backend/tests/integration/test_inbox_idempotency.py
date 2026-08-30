"""Tenant-aware inbox claim, duplicate-delivery, and retry tests."""

from __future__ import annotations

import pytest
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.inbox import InboxConflictError, InboxDisposition

from .support import FIXED_NOW, RecordingDatabase, make_authorization_context, make_event


def test_duplicate_delivery_is_handled_once_for_one_tenant_consumer() -> None:
    database = RecordingDatabase()
    event = make_event()
    process_count = 0

    with PostgresUnitOfWork(
        database.connect, authorization_context=make_authorization_context()
    ) as unit_of_work:
        claim = unit_of_work.inbox.claim(
            consumer_name="timeline-consumer",
            event=event,
            received_at=FIXED_NOW,
        )
        assert claim.disposition == InboxDisposition.CLAIMED
        if claim.should_process:
            process_count += 1
            unit_of_work.inbox.mark_handled(
                consumer_name="timeline-consumer",
                event_id=event.event_id,
                payload_checksum=event.payload_checksum,
                handled_at=FIXED_NOW,
            )

    with PostgresUnitOfWork(
        database.connect, authorization_context=make_authorization_context()
    ) as unit_of_work:
        duplicate = unit_of_work.inbox.claim(
            consumer_name="timeline-consumer",
            event=event,
            received_at=FIXED_NOW,
        )
        assert duplicate.disposition == InboxDisposition.ALREADY_HANDLED
        assert not duplicate.should_process
        if duplicate.should_process:
            process_count += 1

    assert process_count == 1
    assert len(database.inbox) == 1


def test_inbox_claim_rolls_back_with_business_handling_and_can_be_redelivered() -> None:
    database = RecordingDatabase()
    event = make_event()

    with pytest.raises(RuntimeError, match="handler failed"):
        with PostgresUnitOfWork(
            database.connect, authorization_context=make_authorization_context()
        ) as unit_of_work:
            claim = unit_of_work.inbox.claim(consumer_name="case-consumer", event=event)
            assert claim.should_process
            raise RuntimeError("handler failed")

    assert database.inbox == {}
    with PostgresUnitOfWork(
        database.connect, authorization_context=make_authorization_context()
    ) as unit_of_work:
        redelivery = unit_of_work.inbox.claim(consumer_name="case-consumer", event=event)
        assert redelivery.disposition == InboxDisposition.CLAIMED


def test_failed_delivery_can_be_reclaimed_without_changing_delivery_identity() -> None:
    database = RecordingDatabase()
    event = make_event()

    with PostgresUnitOfWork(
        database.connect, authorization_context=make_authorization_context()
    ) as unit_of_work:
        unit_of_work.inbox.claim(consumer_name="case-consumer", event=event)
        failed = unit_of_work.inbox.mark_failed(
            consumer_name="case-consumer",
            event_id=event.event_id,
            payload_checksum=event.payload_checksum,
            error="temporary handler failure",
        )
        assert failed.handling_status == "failed"

    with PostgresUnitOfWork(
        database.connect, authorization_context=make_authorization_context()
    ) as unit_of_work:
        retry = unit_of_work.inbox.claim(consumer_name="case-consumer", event=event)
        assert retry.disposition == InboxDisposition.RETRY
        assert retry.should_process
        handled = unit_of_work.inbox.mark_handled(
            consumer_name="case-consumer",
            event_id=event.event_id,
            payload_checksum=event.payload_checksum,
            handled_at=FIXED_NOW,
        )
        assert handled.handling_status == "handled"


def test_inbox_identity_is_scoped_by_tenant_and_consumer() -> None:
    database = RecordingDatabase()
    event = make_event(event_id="shared-event")
    with PostgresUnitOfWork(
        database.connect, authorization_context=make_authorization_context()
    ) as unit_of_work:
        first = unit_of_work.inbox.claim(consumer_name="projection-a", event=event)
    with PostgresUnitOfWork(
        database.connect, authorization_context=make_authorization_context("tenant-b")
    ) as unit_of_work:
        second = unit_of_work.inbox.claim(
            consumer_name="projection-a",
            event=make_event(tenant_id="tenant-b", event_id="shared-event"),
        )
    with PostgresUnitOfWork(
        database.connect, authorization_context=make_authorization_context()
    ) as unit_of_work:
        other_consumer = unit_of_work.inbox.claim(consumer_name="projection-b", event=event)

    assert first.disposition == InboxDisposition.CLAIMED
    assert second.disposition == InboxDisposition.CLAIMED
    assert other_consumer.disposition == InboxDisposition.CLAIMED
    assert len(database.inbox) == 3


def test_reusing_delivery_identity_with_different_checksum_is_rejected() -> None:
    database = RecordingDatabase()
    with PostgresUnitOfWork(
        database.connect, authorization_context=make_authorization_context()
    ) as unit_of_work:
        unit_of_work.inbox.claim(consumer_name="case-consumer", event=make_event())

    with pytest.raises(InboxConflictError, match="different payload checksum"):
        with PostgresUnitOfWork(
            database.connect, authorization_context=make_authorization_context()
        ) as unit_of_work:
            unit_of_work.inbox.claim(
                consumer_name="case-consumer",
                event=make_event(payload_checksum="sha256:payload-2"),
            )
