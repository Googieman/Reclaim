"""Redpanda-compatible at-least-once event transport adapters."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from packages.contracts.events import EventEnvelope

from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.inbox import InboxDisposition
from app.events.outbox import OutboxEvent

DOMAIN_TOPIC = "reclaim.domain.v1"
DEAD_LETTER_TOPIC = "reclaim.domain.dlq.v1"


class EventTransportError(RuntimeError):
    """Raised when a broker acknowledgement is unavailable."""


class AsyncProducer(Protocol):
    async def send_and_wait(
        self,
        topic: str,
        *,
        key: bytes | None = None,
        value: bytes,
        headers: list[tuple[str, bytes]] | None = None,
    ) -> Any: ...


class EventHandler(Protocol):
    def __call__(self, event: EventEnvelope, unit_of_work: PostgresUnitOfWork) -> Any: ...


@dataclass(frozen=True, slots=True)
class PublishedEvent:
    tenant_id: str
    event_id: str
    outbox_id: str
    topic: str
    broker_metadata: Any


@dataclass(frozen=True, slots=True)
class DispatchResult:
    event_id: str
    tenant_id: str
    disposition: InboxDisposition
    processed: bool


def serialize_event(event: EventEnvelope) -> bytes:
    """Serialize one versioned envelope with deterministic JSON ordering."""

    return json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def deserialize_event(value: bytes | bytearray | str) -> EventEnvelope:
    """Decode broker data through the shared event contract."""

    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise EventTransportError("event payload must be a JSON object")
    return EventEnvelope.model_validate(payload)


def event_headers(event: EventEnvelope) -> list[tuple[str, bytes]]:
    return [
        ("schema_version", event.schema_version.encode("utf-8")),
        ("event_type", event.event_type.value.encode("utf-8")),
        ("tenant_id", event.tenant_id.encode("utf-8")),
        ("payload_checksum", event.payload_checksum.encode("utf-8")),
    ]


class RedpandaOutboxPublisher:
    """Publish durable outbox rows and watermark only broker acknowledgements."""

    def __init__(self, producer: AsyncProducer, *, topic: str = DOMAIN_TOPIC) -> None:
        self.producer = producer
        self.topic = topic

    async def publish_pending(
        self,
        *,
        unit_of_work_factory: Callable[[TenantAuthorizationContext], PostgresUnitOfWork],
        authorization_context: TenantAuthorizationContext,
        limit: int = 100,
        published_at: datetime | None = None,
    ) -> tuple[PublishedEvent, ...]:
        _require_service_context(authorization_context)
        with unit_of_work_factory(authorization_context) as unit_of_work:
            pending = unit_of_work.outbox.unpublished(limit=limit)

        published: list[PublishedEvent] = []
        for outbox_event in pending:
            _require_event_tenant_binding(outbox_event.tenant_id, authorization_context)
            event = _event_from_outbox(outbox_event)
            metadata = await self.producer.send_and_wait(
                self.topic,
                key=event.aggregate_id.encode("utf-8"),
                value=serialize_event(event),
                headers=event_headers(event),
            )
            with unit_of_work_factory(authorization_context) as unit_of_work:
                unit_of_work.outbox.mark_published(
                    outbox_id=outbox_event.outbox_id,
                    published_at=published_at,
                )
            published.append(
                PublishedEvent(
                    tenant_id=authorization_context.tenant_id,
                    event_id=event.event_id,
                    outbox_id=outbox_event.outbox_id,
                    topic=self.topic,
                    broker_metadata=metadata,
                )
            )
        return tuple(published)


class RedpandaInboxDispatcher:
    """Claim, handle, and acknowledge messages through one tenant UoW."""

    def __init__(self, *, consumer_name: str) -> None:
        if not consumer_name.strip():
            raise ValueError("consumer_name is required")
        self.consumer_name = consumer_name

    async def dispatch(
        self,
        value: bytes | bytearray | str,
        *,
        unit_of_work_factory: Callable[[TenantAuthorizationContext], PostgresUnitOfWork],
        authorization_context: TenantAuthorizationContext,
        handler: EventHandler,
        received_at: datetime | None = None,
    ) -> DispatchResult:
        event = deserialize_event(value)
        _require_service_context(authorization_context)
        _require_event_tenant_binding(event.tenant_id, authorization_context)
        try:
            with unit_of_work_factory(authorization_context) as unit_of_work:
                claim = unit_of_work.inbox.claim(
                    consumer_name=self.consumer_name,
                    event=event,
                    received_at=received_at,
                )
                if not claim.should_process:
                    return DispatchResult(
                        event_id=event.event_id,
                        tenant_id=event.tenant_id,
                        disposition=claim.disposition,
                        processed=False,
                    )
                result = handler(event, unit_of_work)
                if inspect.isawaitable(result):
                    await result
                unit_of_work.inbox.mark_handled(
                    consumer_name=self.consumer_name,
                    event_id=event.event_id,
                    payload_checksum=event.payload_checksum,
                    handled_at=received_at,
                )
                return DispatchResult(
                    event_id=event.event_id,
                    tenant_id=event.tenant_id,
                    disposition=claim.disposition,
                    processed=True,
                )
        except Exception as exc:
            self._record_failed_claim(
                event,
                unit_of_work_factory=unit_of_work_factory,
                authorization_context=authorization_context,
                error=str(exc),
                received_at=received_at,
            )
            raise

    def _record_failed_claim(
        self,
        event: EventEnvelope,
        *,
        unit_of_work_factory: Callable[[TenantAuthorizationContext], PostgresUnitOfWork],
        authorization_context: TenantAuthorizationContext,
        error: str,
        received_at: datetime | None,
    ) -> None:
        with unit_of_work_factory(authorization_context) as unit_of_work:
            claim = unit_of_work.inbox.claim(
                consumer_name=self.consumer_name,
                event=event,
                received_at=received_at,
            )
            if claim.message.handling_status == "received":
                unit_of_work.inbox.mark_failed(
                    consumer_name=self.consumer_name,
                    event_id=event.event_id,
                    payload_checksum=event.payload_checksum,
                    error=error or "event handler failed",
                )


def _require_service_context(context: TenantAuthorizationContext) -> None:
    if context.identity_type is not IdentityType.SERVICE:
        raise EventTransportError("event consumers require an authenticated service context")


def _require_event_tenant_binding(
    event_tenant_id: str, authorization_context: TenantAuthorizationContext
) -> None:
    if event_tenant_id != authorization_context.tenant_id:
        raise EventTransportError(
            "event tenant does not match the authenticated service context"
        )


def _event_from_outbox(outbox_event: OutboxEvent) -> EventEnvelope:
    return EventEnvelope(
        tenant_id=outbox_event.tenant_id,
        correlation_id=outbox_event.correlation_id,
        event_id=outbox_event.event_id,
        event_type=outbox_event.event_type,
        aggregate_type=outbox_event.aggregate_type,
        aggregate_id=outbox_event.aggregate_id,
        occurred_at=outbox_event.occurred_at,
        produced_at=outbox_event.produced_at,
        causation_id=outbox_event.causation_id,
        producer=outbox_event.producer,
        payload_checksum=outbox_event.payload_checksum,
        payload=outbox_event.payload,
    )
