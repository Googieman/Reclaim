"""US1 incident-domain event builders and tenant-bound delivery consumer."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from packages.contracts.events import EventEnvelope, EventType

from app.auth.oidc import TenantAuthorizationContext
from app.db.unit_of_work import PostgresUnitOfWork

from .authority import payload_checksum, validate_payload_checksum
from .redpanda import DispatchResult, RedpandaInboxDispatcher

EventHandler = Callable[[EventEnvelope, PostgresUnitOfWork], Any]


class EventContractError(ValueError):
    """Raised when a valid envelope carries an invalid family payload."""


def build_incident_accepted_event(
    *,
    tenant_id: str,
    correlation_id: str,
    incident_id: str,
    case_id: str,
    source: str,
    received_at: datetime,
    report_reference: str | None,
    report_content_present: bool,
    causation_id: str,
    producer: str,
) -> EventEnvelope:
    """Build the metadata-only event emitted with an accepted incident."""

    payload: dict[str, Any] = {
        "incident_id": incident_id,
        "case_id": case_id,
        "source": source,
        "received_at": received_at.isoformat(),
        "report_reference": report_reference,
        "report_content_present": report_content_present,
    }
    return EventEnvelope(
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        event_id=f"incident.accepted:{incident_id}",
        event_type=EventType.INCIDENT_ACCEPTED,
        aggregate_type="incident",
        aggregate_id=incident_id,
        occurred_at=received_at,
        produced_at=received_at,
        causation_id=causation_id,
        producer=producer,
        payload_checksum=payload_checksum(payload),
        payload=payload,
    )


def build_webhook_quarantined_event(
    *,
    tenant_id: str,
    correlation_id: str,
    quarantine_id: str,
    connector_id: str,
    provider_event_id: str | None,
    raw_payload_checksum: str,
    reason: str,
    recorded_at: datetime,
    causation_id: str,
    producer: str,
) -> EventEnvelope:
    """Build a quarantine event without placing raw webhook bytes on Redpanda."""

    payload: dict[str, Any] = {
        "connector_id": connector_id,
        "quarantine_id": quarantine_id,
        "provider_event_id": provider_event_id,
        "payload_checksum": raw_payload_checksum,
        "reason": reason,
    }
    return EventEnvelope(
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        event_id=f"webhook.quarantined:{quarantine_id}",
        event_type=EventType.WEBHOOK_QUARANTINED,
        aggregate_type="webhook",
        aggregate_id=quarantine_id,
        occurred_at=recorded_at,
        produced_at=recorded_at,
        causation_id=causation_id,
        producer=producer,
        payload_checksum=payload_checksum(payload),
        payload=payload,
    )


class IncidentEventConsumer:
    """Consume incident-family events through the tenant-scoped PostgreSQL inbox."""

    EVENT_TYPES = frozenset({EventType.INCIDENT_ACCEPTED, EventType.WEBHOOK_QUARANTINED})

    def __init__(
        self,
        *,
        consumer_name: str = "us1-incident-events",
        handler: EventHandler | None = None,
    ) -> None:
        self._dispatcher = RedpandaInboxDispatcher(consumer_name=consumer_name)
        self.handler = handler

    async def dispatch(
        self,
        value: bytes | bytearray | str,
        *,
        unit_of_work_factory: Callable[[TenantAuthorizationContext], PostgresUnitOfWork],
        authorization_context: TenantAuthorizationContext,
        received_at: datetime | None = None,
    ) -> DispatchResult:
        return await self._dispatcher.dispatch(
            value,
            unit_of_work_factory=unit_of_work_factory,
            authorization_context=authorization_context,
            handler=self.handle,
            received_at=received_at,
        )

    async def consume(self, *args: Any, **kwargs: Any) -> DispatchResult:
        """Alias for broker adapters that call consumers rather than dispatchers."""

        return await self.dispatch(*args, **kwargs)

    async def handle(self, event: EventEnvelope, unit_of_work: PostgresUnitOfWork) -> None:
        if event.event_type not in self.EVENT_TYPES:
            raise EventContractError("incident consumer received an unsupported event family")
        validate_payload_checksum(event)
        _validate_incident_event(event)
        if self.handler is not None:
            result = self.handler(event, unit_of_work)
            if hasattr(result, "__await__"):
                await result


def _validate_incident_event(event: EventEnvelope) -> None:
    payload = event.payload
    if event.event_type is EventType.INCIDENT_ACCEPTED:
        _require_payload_identity(payload, "incident_id", event.aggregate_id)
        _require_text(payload, "case_id")
        if event.aggregate_type != "incident":
            raise EventContractError("incident.accepted aggregate type is invalid")
        return
    _require_payload_identity(payload, "quarantine_id", event.aggregate_id)
    _require_text(payload, "connector_id")
    _require_text(payload, "reason")
    if event.aggregate_type != "webhook":
        raise EventContractError("webhook.quarantined aggregate type is invalid")


def _require_payload_identity(payload: Mapping[str, Any], name: str, expected: str) -> None:
    value = payload.get(name)
    if value != expected:
        raise EventContractError(f"event payload {name} does not match envelope aggregate")


def _require_text(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise EventContractError(f"event payload {name} is required")
    return value


__all__ = [
    "EventContractError",
    "IncidentEventConsumer",
    "build_incident_accepted_event",
    "build_webhook_quarantined_event",
    "payload_checksum",
    "validate_payload_checksum",
]
