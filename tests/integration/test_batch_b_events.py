"""Remediation Batch B event-authority and projection-poisoning coverage."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Self
from uuid import uuid4

import pytest
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.authority import payload_checksum
from app.events.redpanda import (
    EventTransportError,
    RedpandaInboxDispatcher,
    serialize_event,
)
from app.events.incident_events import (
    IncidentEventConsumer,
    build_incident_accepted_event,
)
from app.events.outbox import OutboxAuthorityError
from packages.contracts.events import EventType
from projections.neo4j_case_projection import (
    Neo4jCaseProjection,
    Neo4jCaseProjectionConsumer,
)

from backend.tests.integration.support import (
    RecordingDatabase,
    make_authorization_context,
)


NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


def incident_event(
    *,
    tenant_id: str = "tenant-a",
    incident_id: str = "incident-1",
    case_id: str = "case-1",
    producer: str = "intake-api@1.0.0",
):
    return build_incident_accepted_event(
        tenant_id=tenant_id,
        correlation_id=f"corr-{case_id}",
        incident_id=incident_id,
        case_id=case_id,
        source="operator",
        received_at=NOW,
        report_reference=None,
        report_content_present=True,
        causation_id=f"intake-{incident_id}",
        producer=producer,
    )


def database_factory(database: RecordingDatabase):
    return lambda context: PostgresUnitOfWork(
        database.connect,
        authorization_context=context,
    )


@pytest.mark.asyncio
async def test_forged_correctly_checksummed_event_is_rejected_before_handler() -> None:
    database = RecordingDatabase()
    event = incident_event(incident_id="forged", case_id="forged-case")
    handled: list[str] = []

    consumer = IncidentEventConsumer(
        handler=lambda value, _uow: handled.append(value.event_id)
    )
    with pytest.raises(
        OutboxAuthorityError, match="no authoritative PostgreSQL outbox row"
    ):
        await consumer.dispatch(
            serialize_event(event),
            unit_of_work_factory=database_factory(database),
            authorization_context=make_authorization_context(),
        )

    assert event.payload_checksum == payload_checksum(event.payload)
    assert handled == []
    assert database.outbox == {}
    assert (
        database.inbox[("tenant-a", "us1-incident-events", event.event_id)][6]
        == "failed"
    )


@pytest.mark.asyncio
async def test_event_id_collision_with_altered_payload_fails_closed() -> None:
    database = RecordingDatabase()
    authoritative = incident_event()
    database.seed_outbox(authoritative)
    altered_payload = {**authoritative.payload, "case_id": "attacker-case"}
    forged = authoritative.model_copy(
        update={
            "payload": altered_payload,
            "payload_checksum": payload_checksum(altered_payload),
        }
    )
    handled: list[str] = []
    consumer = IncidentEventConsumer(
        handler=lambda value, _uow: handled.append(value.event_id)
    )

    with pytest.raises(
        OutboxAuthorityError,
        match="does not match its authoritative outbox row",
    ):
        await consumer.dispatch(
            serialize_event(forged),
            unit_of_work_factory=database_factory(database),
            authorization_context=make_authorization_context(),
        )

    assert handled == []
    assert (
        database.inbox[("tenant-a", "us1-incident-events", authoritative.event_id)][6]
        == "failed"
    )


@pytest.mark.asyncio
async def test_event_type_and_schema_mismatch_fail_against_outbox_authority() -> None:
    database = RecordingDatabase()
    authoritative = incident_event()
    database.seed_outbox(authoritative)
    consumer = IncidentEventConsumer()

    wrong_type = authoritative.model_copy(
        update={"event_type": EventType.WEBHOOK_QUARANTINED}
    )
    with pytest.raises(
        OutboxAuthorityError,
        match="does not match its authoritative outbox row",
    ):
        await consumer.dispatch(
            serialize_event(wrong_type),
            unit_of_work_factory=database_factory(database),
            authorization_context=make_authorization_context(),
        )

    wrong_schema = authoritative.model_copy(update={"schema_version": "2.0.0"})
    with pytest.raises(
        EventTransportError, match="unsupported authoritative event schema"
    ):
        await consumer.dispatch(
            serialize_event(wrong_schema),
            unit_of_work_factory=database_factory(database),
            authorization_context=make_authorization_context(),
        )


@pytest.mark.asyncio
async def test_cross_tenant_event_substitution_never_reaches_database() -> None:
    event = incident_event(tenant_id="tenant-b")
    factory_calls: list[Any] = []

    def factory(context: Any) -> PostgresUnitOfWork:
        factory_calls.append(context)
        raise AssertionError("cross-tenant event must not open a transaction")

    consumer = IncidentEventConsumer()
    with pytest.raises(EventTransportError, match="tenant"):
        await consumer.dispatch(
            serialize_event(event),
            unit_of_work_factory=factory,
            authorization_context=make_authorization_context("tenant-a"),
        )

    assert factory_calls == []


@pytest.mark.asyncio
async def test_unauthorized_producer_is_rejected_even_with_valid_checksum() -> None:
    database = RecordingDatabase()
    event = incident_event(producer="attacker-service@9.9.9")
    handled: list[str] = []
    consumer = IncidentEventConsumer(
        handler=lambda value, _uow: handled.append(value.event_id)
    )

    with pytest.raises(EventTransportError, match="producer is not allowlisted"):
        await consumer.dispatch(
            serialize_event(event),
            unit_of_work_factory=database_factory(database),
            authorization_context=make_authorization_context(),
        )

    assert event.payload_checksum == payload_checksum(event.payload)
    assert handled == []
    assert (
        database.inbox[("tenant-a", "us1-incident-events", event.event_id)][6]
        == "failed"
    )


@pytest.mark.asyncio
async def test_unauthorized_service_identity_is_rejected_at_consumer_boundary() -> None:
    event = incident_event(incident_id="service", case_id="service-case")
    consumer = IncidentEventConsumer()
    unauthorized = replace(make_authorization_context(), subject="unregistered-service")

    with pytest.raises(
        EventTransportError, match="service identity is not allowlisted"
    ):
        await consumer.dispatch(
            serialize_event(event),
            unit_of_work_factory=database_factory(RecordingDatabase()),
            authorization_context=unauthorized,
        )


class ProjectionSpy:
    def __init__(self) -> None:
        self.applied: list[str] = []

    def apply(self, event: Any, *, consumer_name: str) -> str:
        del consumer_name
        self.applied.append(event.event_id)
        return event.aggregate_id


@pytest.mark.asyncio
async def test_valid_authoritative_event_projects_and_duplicate_is_noop() -> None:
    database = RecordingDatabase()
    event = incident_event()
    database.seed_outbox(event)
    projection = ProjectionSpy()
    consumer = Neo4jCaseProjectionConsumer(projection)
    factory = database_factory(database)
    context = make_authorization_context()

    first = await consumer.dispatch(
        serialize_event(event),
        unit_of_work_factory=factory,
        authorization_context=context,
    )
    duplicate = await consumer.dispatch(
        serialize_event(event),
        unit_of_work_factory=factory,
        authorization_context=context,
    )

    assert first.processed is True
    assert duplicate.processed is False
    assert projection.applied == [event.event_id]


@pytest.mark.asyncio
async def test_out_of_order_authoritative_events_each_apply_once() -> None:
    database = RecordingDatabase()
    newer = incident_event(incident_id="newer", case_id="newer-case")
    older = incident_event(incident_id="older", case_id="older-case")
    database.seed_outbox(newer)
    database.seed_outbox(older)
    handled: list[str] = []
    consumer = IncidentEventConsumer(
        handler=lambda value, _uow: handled.append(value.event_id)
    )
    factory = database_factory(database)
    context = make_authorization_context()

    await consumer.dispatch(
        serialize_event(newer),
        unit_of_work_factory=factory,
        authorization_context=context,
    )
    await consumer.dispatch(
        serialize_event(older),
        unit_of_work_factory=factory,
        authorization_context=context,
    )
    await consumer.dispatch(
        serialize_event(newer),
        unit_of_work_factory=factory,
        authorization_context=context,
    )

    assert handled == [newer.event_id, older.event_id]


class OutageInbox:
    def __init__(self) -> None:
        self.claimed = False

    def claim(self, **_kwargs: object) -> Any:
        self.claimed = True
        return SimpleNamespace(
            should_process=True,
            message=SimpleNamespace(handling_status="received"),
        )

    def mark_handled(self, **_kwargs: object) -> None:
        raise AssertionError("handler and handled transition must not run")

    def mark_failed(self, **_kwargs: object) -> None:
        self.claimed = False


class OutageOutbox:
    def reconcile_authority(self, _event: Any) -> None:
        raise RuntimeError("PostgreSQL unavailable during outbox reconciliation")


class OutageUnitOfWork:
    def __init__(self) -> None:
        self.inbox = OutageInbox()
        self.outbox = OutageOutbox()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback


@pytest.mark.asyncio
async def test_postgresql_outage_during_reconciliation_fails_closed() -> None:
    event = incident_event(incident_id="outage", case_id="outage-case")
    handled: list[str] = []
    dispatcher = RedpandaInboxDispatcher(consumer_name="outage-consumer")

    with pytest.raises(RuntimeError, match="PostgreSQL unavailable"):
        await dispatcher.dispatch(
            serialize_event(event),
            unit_of_work_factory=lambda _context: OutageUnitOfWork(),
            authorization_context=make_authorization_context(),
            handler=lambda value, _uow: handled.append(value.event_id),
        )

    assert handled == []


@pytest.mark.skipif(
    not (
        os.getenv("RECLAIM_DATABASE_URL")
        and os.getenv("RECLAIM_REDPANDA_BROKERS")
        and os.getenv("RECLAIM_NEO4J_URI")
        and os.getenv("RECLAIM_NEO4J_USER")
        and os.getenv("RECLAIM_NEO4J_PASSWORD")
    ),
    reason="live PostgreSQL, Redpanda, and Neo4j are required for Batch B event validation",
)
@pytest.mark.asyncio
async def test_live_forged_event_cannot_poison_neo4j_projection() -> None:
    """A broker message with a valid envelope checksum still needs outbox authority."""

    import psycopg
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    from app.auth.oidc import AuthenticatedPrincipal, IdentityType

    tenant_id = f"batch-b-live-{uuid4().hex}"
    service_context = AuthenticatedPrincipal(
        subject="reclaim-neo4j-projection",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="batch-b-live",
    ).for_tenant(tenant_id)
    database_url = os.environ["RECLAIM_DATABASE_URL"]

    def factory(context):
        return PostgresUnitOfWork(
            lambda: psycopg.connect(database_url),
            authorization_context=context,
        )

    with PostgresUnitOfWork(
        lambda: psycopg.connect(database_url),
        authorization_context=service_context,
    ) as unit_of_work:
        unit_of_work.tenants.create(tenant_id=tenant_id, display_name="Batch B Live")

    event = incident_event(
        tenant_id=tenant_id, incident_id="forged-live", case_id="case-live"
    )
    assert event.payload_checksum == payload_checksum(event.payload)
    group_id = f"batch-b-live-{uuid4().hex}"
    producer = AIOKafkaProducer(
        bootstrap_servers=os.environ["RECLAIM_REDPANDA_BROKERS"]
    )
    consumer = AIOKafkaConsumer(
        "reclaim.domain.v1",
        bootstrap_servers=os.environ["RECLAIM_REDPANDA_BROKERS"],
        group_id=group_id,
        auto_offset_reset="latest",
        enable_auto_commit=False,
    )
    projection = Neo4jCaseProjectionConsumer(
        Neo4jCaseProjection.from_uri(
            os.environ["RECLAIM_NEO4J_URI"],
            username=os.environ["RECLAIM_NEO4J_USER"],
            password=os.environ["RECLAIM_NEO4J_PASSWORD"],
        )
    )
    await producer.start()
    await consumer.start()
    try:
        projection.projection.bootstrap()
        await producer.send_and_wait(
            "reclaim.domain.v1",
            key=event.aggregate_id.encode("utf-8"),
            value=serialize_event(event),
        )
        message = await asyncio.wait_for(consumer.getone(), timeout=15)
        with pytest.raises(
            OutboxAuthorityError, match="no authoritative PostgreSQL outbox row"
        ):
            await projection.dispatch(
                message.value,
                unit_of_work_factory=factory,
                authorization_context=service_context,
            )
        assert projection.projection.checkpoints(tenant_id) == ()
        with psycopg.connect(database_url) as connection:
            outbox_count = connection.execute(
                "SELECT count(*) FROM outbox_events WHERE tenant_id = %s AND event_id = %s",
                (tenant_id, event.event_id),
            ).fetchone()
        assert outbox_count == (0,)
    finally:
        await consumer.stop()
        await producer.stop()
        projection.projection.reset_tenant(tenant_id)
        projection.projection.close()
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "SELECT set_config('reclaim.tenant_id', %s, true)", (tenant_id,)
            )
            connection.execute(
                "DELETE FROM inbox_messages WHERE tenant_id = %s", (tenant_id,)
            )
            connection.execute("DELETE FROM tenants WHERE tenant_id = %s", (tenant_id,))
