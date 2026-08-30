"""T056 outbox-to-Redpanda delivery, retry, and tenant-boundary coverage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Self

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.incident_events import (
    IncidentEventConsumer,
    build_incident_accepted_event,
)
from app.events.outbox import OutboxEvent
from app.events.redpanda import (
    EventTransportError,
    RedpandaOutboxPublisher,
    serialize_event,
)
from app.events.timeline_events import TimelineEventConsumer
from evidence.models import CollectedEvidence, EvidenceProvenance

from backend.tests.integration.support import (
    RecordingDatabase,
    make_authorization_context,
)


NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


def user_context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="reviewer-1",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"reviewer"})},
        identity_type=IdentityType.USER,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


def incident_event(
    *,
    tenant_id: str = "tenant-a",
    incident_id: str = "incident-1",
    case_id: str = "case-1",
):
    return build_incident_accepted_event(
        tenant_id=tenant_id,
        correlation_id=f"correlation-{case_id}",
        incident_id=incident_id,
        case_id=case_id,
        source="operator",
        received_at=NOW,
        report_reference=None,
        report_content_present=True,
        causation_id=f"intake-{incident_id}",
        producer="intake-api@1.0.0",
    )


class RecordingProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes, list[tuple[str, bytes]] | None]] = []

    async def send_and_wait(
        self,
        topic: str,
        *,
        key: bytes,
        value: bytes,
        headers: list[tuple[str, bytes]] | None,
    ) -> str:
        self.sent.append((topic, value, headers))
        return "partition-0-offset-1"


class FailingProducer:
    async def send_and_wait(self, topic: str, **kwargs: object) -> None:
        del topic, kwargs
        raise RuntimeError("broker unavailable")


class OneEventOutbox:
    def __init__(self, event: OutboxEvent) -> None:
        self.event = event
        self.published = False

    def unpublished(self, *, limit: int) -> list[OutboxEvent]:
        del limit
        return [] if self.published else [self.event]

    def mark_published(self, *, outbox_id: str, published_at: object) -> OutboxEvent:
        del published_at
        assert outbox_id == self.event.outbox_id
        self.published = True
        return self.event


class PublisherUnitOfWork:
    def __init__(self, outbox: OneEventOutbox) -> None:
        self.outbox = outbox

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback


def outbox_row(event: Any) -> OutboxEvent:
    return OutboxEvent(
        tenant_id=event.tenant_id,
        outbox_id=f"outbox-{event.event_id}",
        event_id=event.event_id,
        event_type=event.event_type.value,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        occurred_at=event.occurred_at,
        produced_at=event.produced_at,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        producer=event.producer,
        payload_checksum=event.payload_checksum,
        payload=event.payload,
        published_at=None,
        created_at=NOW,
    )


@pytest.mark.asyncio
async def test_outbox_publisher_only_watermarks_after_broker_ack() -> None:
    event = incident_event()
    outbox = OneEventOutbox(outbox_row(event))
    producer = RecordingProducer()
    publisher = RedpandaOutboxPublisher(producer)

    published = await publisher.publish_pending(
        unit_of_work_factory=lambda _context: PublisherUnitOfWork(outbox),
        authorization_context=make_authorization_context(),
    )

    assert len(published) == 1
    assert outbox.published is True
    assert producer.sent[0][0] == "reclaim.domain.v1"
    assert dict(producer.sent[0][2] or [])["tenant_id"] == b"tenant-a"


@pytest.mark.asyncio
async def test_outbox_publisher_leaves_row_pending_when_broker_ack_fails() -> None:
    event = incident_event()
    outbox = OneEventOutbox(outbox_row(event))

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await RedpandaOutboxPublisher(FailingProducer()).publish_pending(
            unit_of_work_factory=lambda _context: PublisherUnitOfWork(outbox),
            authorization_context=make_authorization_context(),
        )

    assert outbox.published is False


@pytest.mark.asyncio
async def test_incident_consumer_handles_duplicate_and_out_of_order_delivery_once() -> (
    None
):
    database = RecordingDatabase()
    handled: list[str] = []
    consumer = IncidentEventConsumer(
        handler=lambda event, _unit_of_work: handled.append(event.event_id)
    )

    def factory(context: Any) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(database.connect, authorization_context=context)

    newer = incident_event(incident_id="incident-new", case_id="case-new")
    older = incident_event(incident_id="incident-old", case_id="case-old")
    await consumer.dispatch(
        serialize_event(newer),
        unit_of_work_factory=factory,
        authorization_context=make_authorization_context(),
    )
    await consumer.dispatch(
        serialize_event(older),
        unit_of_work_factory=factory,
        authorization_context=make_authorization_context(),
    )
    duplicate = await consumer.dispatch(
        serialize_event(newer),
        unit_of_work_factory=factory,
        authorization_context=make_authorization_context(),
    )

    assert handled == [newer.event_id, older.event_id]
    assert duplicate.processed is False
    assert len(database.inbox) == 2


@pytest.mark.asyncio
async def test_timeline_consumer_retries_failed_delivery_without_losing_identity() -> (
    None
):
    database = RecordingDatabase()
    attempts = 0

    def flaky_handler(_event: object, _unit_of_work: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary projection failure")

    item = CollectedEvidence(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        evidence_id="evidence-1",
        connector_id="sim-sessions",
        resource_type="sessions",
        source_identifier="session-event-1",
        source_identity="merchant-sessions",
        observed_at=NOW,
        received_at=NOW,
        raw_object_uri="minio://reclaim/evidence-1",
        raw_checksum="sha256:evidence-1",
        expected_checksum="sha256:evidence-1",
        completeness="complete",
        normalization_status="normalized",
        integrity_status="verified",
        provenance=EvidenceProvenance(
            tenant_id="tenant-a",
            case_id="case-1",
            correlation_id="corr-1",
            connector_id="sim-sessions",
            resource_type="sessions",
            source_identity="merchant-sessions",
            mode="replay",
            source="fixture",
            version="1.0.0",
            seed="seed-1",
            evidence_id="evidence-1",
            raw_checksum="sha256:evidence-1",
        ),
    )
    from app.events.timeline_events import build_evidence_collected_event

    event = build_evidence_collected_event(item)
    consumer = TimelineEventConsumer(handler=flaky_handler)

    def factory(context: Any) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(database.connect, authorization_context=context)

    with pytest.raises(RuntimeError, match="temporary projection failure"):
        await consumer.dispatch(
            serialize_event(event),
            unit_of_work_factory=factory,
            authorization_context=make_authorization_context(),
        )
    assert (
        database.inbox[("tenant-a", "us1-timeline-events", event.event_id)][6]
        == "failed"
    )

    retry = await consumer.dispatch(
        serialize_event(event),
        unit_of_work_factory=factory,
        authorization_context=make_authorization_context(),
    )
    assert retry.processed is True
    assert retry.disposition.value == "retry"
    assert (
        database.inbox[("tenant-a", "us1-timeline-events", event.event_id)][6]
        == "handled"
    )
    assert attempts == 2


@pytest.mark.asyncio
async def test_consumer_rejects_bad_payload_checksum_and_cross_tenant_delivery() -> (
    None
):
    database = RecordingDatabase()
    consumer = IncidentEventConsumer()

    def factory(context: Any) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(database.connect, authorization_context=context)

    event = incident_event()
    tampered = event.model_copy(update={"payload": {"incident_id": "poisoned"}})

    with pytest.raises(ValueError, match="payload checksum"):
        await consumer.dispatch(
            serialize_event(tampered),
            unit_of_work_factory=factory,
            authorization_context=make_authorization_context(),
        )

    with pytest.raises(EventTransportError, match="tenant"):
        await consumer.dispatch(
            serialize_event(incident_event(tenant_id="tenant-b")),
            unit_of_work_factory=factory,
            authorization_context=make_authorization_context("tenant-a"),
        )

    failed_key = ("tenant-a", "us1-incident-events", event.event_id)
    assert database.inbox[failed_key][6] == "failed"
