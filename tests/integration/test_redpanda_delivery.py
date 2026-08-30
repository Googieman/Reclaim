"""Redpanda transport tests using the durable outbox/inbox protocol doubles."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Self

import pytest
from app.events.inbox import InboxDisposition
from app.events.outbox import OutboxEvent
from app.events.redpanda import (
    RedpandaInboxDispatcher,
    RedpandaOutboxPublisher,
    deserialize_event,
    serialize_event,
)

from backend.tests.integration.support import make_authorization_context, make_event


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []

    async def send_and_wait(
        self, topic: str, *, key: bytes, value: bytes, headers: object
    ) -> str:
        self.sent.append((topic, value))
        return "partition-0-offset-1"


class FakeOutbox:
    def __init__(self, event: OutboxEvent) -> None:
        self.event = event
        self.published = False

    def unpublished(self, *, limit: int) -> list[OutboxEvent]:
        return [] if self.published else [self.event]

    def mark_published(self, *, outbox_id: str, published_at: object) -> OutboxEvent:
        assert outbox_id == self.event.outbox_id
        self.published = True
        return self.event


class FakeInbox:
    def __init__(self) -> None:
        self.status: dict[tuple[str, str], str] = {}

    def claim(
        self, *, consumer_name: str, event: object, received_at: object
    ) -> object:
        key = (consumer_name, event.event_id)
        status = self.status.get(key)
        if status == "handled":
            return SimpleNamespace(
                disposition=InboxDisposition.ALREADY_HANDLED,
                should_process=False,
                message=SimpleNamespace(handling_status="handled"),
            )
        self.status[key] = "received"
        return SimpleNamespace(
            disposition=InboxDisposition.CLAIMED,
            should_process=True,
            message=SimpleNamespace(handling_status="received"),
        )

    def mark_handled(
        self,
        *,
        consumer_name: str,
        event_id: str,
        payload_checksum: str,
        handled_at: object,
    ) -> None:
        self.status[(consumer_name, event_id)] = "handled"

    def mark_failed(self, **kwargs: object) -> None:
        self.status[(str(kwargs["consumer_name"]), str(kwargs["event_id"]))] = "failed"


class FakeUnitOfWork:
    def __init__(
        self, outbox: FakeOutbox | None = None, inbox: FakeInbox | None = None
    ) -> None:
        self.outbox = outbox
        self.inbox = inbox

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


def test_event_serialization_is_contract_round_trip() -> None:
    event = make_event()
    assert deserialize_event(serialize_event(event)) == event


@pytest.mark.asyncio
async def test_outbox_publisher_marks_only_broker_acknowledged_rows() -> None:
    event = make_event()
    outbox_event = OutboxEvent(
        tenant_id=event.tenant_id,
        outbox_id="outbox-1",
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
        created_at=datetime(2026, 8, 30, tzinfo=UTC),
    )
    outbox = FakeOutbox(outbox_event)
    producer = FakeProducer()
    publisher = RedpandaOutboxPublisher(producer)

    result = await publisher.publish_pending(
        unit_of_work_factory=lambda _context: FakeUnitOfWork(outbox=outbox),
        authorization_context=make_authorization_context(),
    )

    assert len(result) == 1
    assert outbox.published
    assert producer.sent[0][0] == "reclaim.domain.v1"


@pytest.mark.asyncio
async def test_inbox_dispatcher_handles_duplicate_and_out_of_order_messages_once() -> (
    None
):
    inbox = FakeInbox()
    dispatcher = RedpandaInboxDispatcher(consumer_name="timeline")
    handled: list[str] = []

    async def handler(event: object, unit_of_work: object) -> None:
        handled.append(event.event_id)

    newer = make_event(event_id="event-newer")
    older = make_event(event_id="event-older")
    factory = lambda _context: FakeUnitOfWork(inbox=inbox)
    authorization_context = make_authorization_context()
    await dispatcher.dispatch(
        serialize_event(newer),
        unit_of_work_factory=factory,
        authorization_context=authorization_context,
        handler=handler,
    )
    await dispatcher.dispatch(
        serialize_event(older),
        unit_of_work_factory=factory,
        authorization_context=authorization_context,
        handler=handler,
    )
    duplicate = await dispatcher.dispatch(
        serialize_event(newer),
        unit_of_work_factory=factory,
        authorization_context=authorization_context,
        handler=handler,
    )

    assert handled == ["event-newer", "event-older"]
    assert duplicate.disposition is InboxDisposition.ALREADY_HANDLED


@pytest.mark.asyncio
async def test_live_redpanda_round_trip_if_broker_is_configured() -> None:
    brokers = os.getenv("RECLAIM_REDPANDA_BROKERS")
    if not brokers:
        pytest.skip("RECLAIM_REDPANDA_BROKERS is required for live Redpanda validation")
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

    topic = "reclaim.domain.v1"
    group_id = f"reclaim-live-test-{datetime.now(UTC).timestamp()}"
    event = make_event(event_id=f"redpanda-{datetime.now(UTC).timestamp()}")
    producer = AIOKafkaProducer(bootstrap_servers=brokers)
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=brokers,
        group_id=group_id,
        auto_offset_reset="latest",
        enable_auto_commit=False,
    )
    await producer.start()
    await consumer.start()
    try:
        await producer.send_and_wait(
            topic, key=event.aggregate_id.encode(), value=serialize_event(event)
        )
        received = await consumer.getone()
        assert deserialize_event(received.value).event_id == event.event_id
    finally:
        await consumer.stop()
        await producer.stop()
