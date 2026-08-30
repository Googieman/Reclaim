"""Transactional outbox persistence for authoritative PostgreSQL transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from packages.contracts.events import EventEnvelope

from app.db.repositories.base import RepositoryError, TenantScopedRepository


class OutboxConflictError(RepositoryError):
    """Raised when an event identity is reused with different event content."""


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """The durable event hand-off record returned by an enqueue operation."""

    tenant_id: str
    outbox_id: str
    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    occurred_at: datetime
    produced_at: datetime
    correlation_id: str
    causation_id: str
    producer: str
    payload_checksum: str
    payload: dict[str, Any]
    published_at: datetime | None
    created_at: datetime
    inserted: bool = True


class OutboxEventRepository(TenantScopedRepository):
    """Write events to the outbox using the caller's existing PostgreSQL transaction.

    The repository deliberately has no publish or acknowledgement method.  Event
    transport is a later boundary; this store only makes the event durable with the
    originating business-state transaction.
    """

    def enqueue(self, *, outbox_id: str, event: EventEnvelope) -> OutboxEvent:
        self.assert_tenant(event.tenant_id)
        if not outbox_id.strip():
            raise RepositoryError("outbox_id is required")

        inserted_row = self.fetch_one(
            """
            INSERT INTO outbox_events (
                tenant_id, outbox_id, event_id, event_type, aggregate_type, aggregate_id,
                occurred_at, produced_at, correlation_id, causation_id, producer,
                payload_checksum, payload
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
            )
            ON CONFLICT (tenant_id, event_id) DO NOTHING
            RETURNING tenant_id, outbox_id, event_id, event_type, aggregate_type,
                      aggregate_id, occurred_at, produced_at, correlation_id,
                      causation_id, producer, payload_checksum, payload,
                      published_at, created_at
            """,
            _event_parameters(outbox_id=outbox_id, event=event),
        )
        if inserted_row is not None:
            return _event_from_row(inserted_row)

        existing_row = self.fetch_one(
            """
            SELECT tenant_id, outbox_id, event_id, event_type, aggregate_type,
                   aggregate_id, occurred_at, produced_at, correlation_id,
                   causation_id, producer, payload_checksum, payload,
                   published_at, created_at
            FROM outbox_events
            WHERE tenant_id = %s AND event_id = %s
            """,
            (self.tenant_context.tenant_id, event.event_id),
        )
        if existing_row is None:
            raise RepositoryError("outbox event disappeared after conflict")

        existing = _event_from_row(existing_row, inserted=False)
        if not _same_event(existing, event):
            raise OutboxConflictError(
                f"outbox event_id {event.event_id!r} already exists with different content"
            )
        return existing


def _event_parameters(*, outbox_id: str, event: EventEnvelope) -> tuple[object, ...]:
    return (
        event.tenant_id,
        outbox_id,
        event.event_id,
        event.event_type.value,
        event.aggregate_type,
        event.aggregate_id,
        event.occurred_at,
        event.produced_at,
        event.correlation_id,
        event.causation_id,
        event.producer,
        event.payload_checksum,
        json.dumps(event.payload, sort_keys=True, separators=(",", ":")),
    )


def _event_from_row(row: Any, *, inserted: bool = True) -> OutboxEvent:
    payload = row[12]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return OutboxEvent(
        tenant_id=str(row[0]),
        outbox_id=str(row[1]),
        event_id=str(row[2]),
        event_type=str(row[3]),
        aggregate_type=str(row[4]),
        aggregate_id=str(row[5]),
        occurred_at=row[6],
        produced_at=row[7],
        correlation_id=str(row[8]),
        causation_id=str(row[9]),
        producer=str(row[10]),
        payload_checksum=str(row[11]),
        payload=dict(payload),
        published_at=row[13],
        created_at=row[14],
        inserted=inserted,
    )


def _same_event(existing: OutboxEvent, event: EventEnvelope) -> bool:
    return (
        existing.tenant_id == event.tenant_id
        and existing.event_id == event.event_id
        and existing.event_type == event.event_type.value
        and existing.aggregate_type == event.aggregate_type
        and existing.aggregate_id == event.aggregate_id
        and existing.occurred_at == event.occurred_at
        and existing.produced_at == event.produced_at
        and existing.correlation_id == event.correlation_id
        and existing.causation_id == event.causation_id
        and existing.producer == event.producer
        and existing.payload_checksum == event.payload_checksum
        and existing.payload == event.payload
    )
