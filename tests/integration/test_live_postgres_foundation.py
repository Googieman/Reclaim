"""Opt-in live PostgreSQL validation for the T022/T023 repository semantics."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.inbox import InboxDisposition

from backend.tests.integration.support import make_authorization_context, make_event

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("RECLAIM_DATABASE_URL")
    if not value:
        pytest.skip("RECLAIM_DATABASE_URL is required for live PostgreSQL validation")
    return value


def test_live_postgres_uow_commits_business_outbox_and_inbox_together() -> None:
    import psycopg

    database_url = _database_url()
    tenant_id = f"live-{uuid.uuid4().hex}"
    incident_id = f"incident-{uuid.uuid4().hex}"
    event = make_event(tenant_id=tenant_id, event_id=f"event-{uuid.uuid4().hex}")

    with PostgresUnitOfWork(
        lambda: psycopg.connect(database_url),
        authorization_context=make_authorization_context(tenant_id),
    ) as unit_of_work:
        unit_of_work.tenants.create(tenant_id=tenant_id, display_name="Live Validation")
        unit_of_work.incidents.create(
            incident_id=incident_id,
            source="live-validation",
            reporter_context={},
            received_at=datetime.now(UTC),
            correlation_key=f"correlation-{incident_id}",
            raw_input_reference=None,
            intake_status="accepted",
            deduplication_identity=f"dedupe-{incident_id}",
        )
        unit_of_work.outbox.enqueue(outbox_id=f"outbox-{uuid.uuid4().hex}", event=event)
        claim = unit_of_work.inbox.claim(consumer_name="live-consumer", event=event)
        assert claim.disposition is InboxDisposition.CLAIMED
        unit_of_work.inbox.mark_handled(
            consumer_name="live-consumer",
            event_id=event.event_id,
            payload_checksum=event.payload_checksum,
        )

    with psycopg.connect(database_url) as connection:
        counts = connection.execute(
            "SELECT (SELECT count(*) FROM incidents WHERE tenant_id=%s), (SELECT count(*) FROM outbox_events WHERE tenant_id=%s), (SELECT count(*) FROM inbox_messages WHERE tenant_id=%s)",
            (tenant_id, tenant_id, tenant_id),
        ).fetchone()
    assert counts == (1, 1, 1)


def test_live_postgres_uow_rolls_back_business_and_delivery_rows() -> None:
    import psycopg

    database_url = _database_url()
    tenant_id = f"rollback-{uuid.uuid4().hex}"
    incident_id = f"incident-{uuid.uuid4().hex}"
    event = make_event(tenant_id=tenant_id, event_id=f"event-{uuid.uuid4().hex}")

    with (
        pytest.raises(RuntimeError, match="rollback-check"),
        PostgresUnitOfWork(
            lambda: psycopg.connect(database_url),
            authorization_context=make_authorization_context(tenant_id),
        ) as unit_of_work,
    ):
        unit_of_work.tenants.create(
            tenant_id=tenant_id, display_name="Rollback Validation"
        )
        unit_of_work.incidents.create(
            incident_id=incident_id,
            source="live-validation",
            reporter_context={},
            received_at=datetime.now(UTC),
            correlation_key=f"correlation-{incident_id}",
            raw_input_reference=None,
            intake_status="accepted",
            deduplication_identity=f"dedupe-{incident_id}",
        )
        unit_of_work.outbox.enqueue(outbox_id=f"outbox-{uuid.uuid4().hex}", event=event)
        unit_of_work.inbox.claim(consumer_name="live-consumer", event=event)
        raise RuntimeError("rollback-check")

    with psycopg.connect(database_url) as connection:
        counts = connection.execute(
            "SELECT (SELECT count(*) FROM tenants WHERE tenant_id=%s), (SELECT count(*) FROM incidents WHERE tenant_id=%s), (SELECT count(*) FROM outbox_events WHERE tenant_id=%s), (SELECT count(*) FROM inbox_messages WHERE tenant_id=%s)",
            (tenant_id, tenant_id, tenant_id, tenant_id),
        ).fetchone()
    assert counts == (0, 0, 0, 0)
