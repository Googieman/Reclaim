"""US1 evidence/timeline event builders and tenant-bound delivery consumer."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from packages.contracts.events import EventEnvelope, EventType

from app.auth.oidc import TenantAuthorizationContext
from app.db.unit_of_work import PostgresUnitOfWork

from .incident_events import EventContractError, payload_checksum, validate_payload_checksum
from .redpanda import DispatchResult, RedpandaInboxDispatcher

if TYPE_CHECKING:
    from evidence.models import CollectedEvidence
    from timeline.models import TimelineEvent, TimelineRebuildResult

EventHandler = Callable[[EventEnvelope, PostgresUnitOfWork], Any]


def build_evidence_collected_event(
    item: CollectedEvidence,
    *,
    producer: str = "evidence-orchestrator@1.0.0",
) -> EventEnvelope:
    """Build one stable event for one collected item, including no raw evidence bytes."""

    provenance = item.provenance
    payload: dict[str, Any] = {
        "case_id": item.case_id,
        "evidence_id": item.evidence_id,
        "connector_id": item.connector_id,
        "resource_type": item.resource_type,
        "source_identifier": item.source_identifier,
        "source_identity": item.source_identity,
        "observed_at": item.observed_at.isoformat(),
        "received_at": item.received_at.isoformat(),
        "raw_object_uri": item.raw_object_uri,
        "raw_checksum": item.raw_checksum,
        "expected_checksum": item.expected_checksum,
        "completeness": item.completeness,
        "normalization_status": item.normalization_status,
        "integrity_status": item.integrity_status,
        "trust_classification": item.trust_classification,
        "collection_error": item.collection_error,
        "normalized_facts": [
            {
                "source_event_id": fact.source_event_id,
                "canonical_event_type": fact.canonical_event_type,
                "dedupe_key": fact.dedupe_key,
                "effective_at": fact.effective_at.isoformat(),
                "evidence_references": list(fact.evidence_references),
                "provider_identifiers": dict(fact.provider_identifiers),
            }
            for fact in item.normalized_facts
        ],
        "provenance": None
        if provenance is None
        else {
            "mode": provenance.mode,
            "source": provenance.source,
            "version": provenance.version,
            "seed": provenance.seed,
            "raw_checksum": provenance.raw_checksum,
            "original_timestamps": dict(provenance.original_timestamps),
        },
    }
    return EventEnvelope(
        tenant_id=item.tenant_id,
        correlation_id=item.correlation_id,
        event_id=f"evidence.collected:{item.evidence_id}",
        event_type=EventType.EVIDENCE_COLLECTED,
        aggregate_type="case",
        aggregate_id=item.case_id,
        occurred_at=item.observed_at,
        produced_at=item.received_at,
        causation_id=f"evidence-collection:{item.case_id}",
        producer=producer,
        payload_checksum=payload_checksum(payload),
        payload=payload,
    )


def build_timeline_rebuilt_event(
    result: TimelineRebuildResult,
    *,
    producer: str = "timeline-reconstructor@1.0.0",
    correlation_id: str | None = None,
) -> EventEnvelope:
    """Build a deterministic rebuild event whose identity converges on equal output."""

    events = [_timeline_payload(event) for event in result.events]
    payload: dict[str, Any] = {
        "case_id": result.case_id,
        "state": result.state,
        "event_count": len(events),
        "uncertainty": list(result.uncertainty),
        "events": events,
        "authoritative_store": result.authoritative_store,
        "event_handoff": result.event_handoff,
    }
    checksum = payload_checksum(payload)
    occurred_at = max(
        (event.effective_at for event in result.events),
        default=datetime(1970, 1, 1, tzinfo=UTC),
    )
    return EventEnvelope(
        tenant_id=result.tenant_id,
        correlation_id=correlation_id or f"case:{result.case_id}",
        event_id=f"timeline.rebuilt:{result.case_id}:{checksum}",
        event_type=EventType.TIMELINE_REBUILT,
        aggregate_type="case",
        aggregate_id=result.case_id,
        occurred_at=occurred_at,
        produced_at=occurred_at,
        causation_id=f"timeline-reconstruction:{result.case_id}",
        producer=producer,
        payload_checksum=checksum,
        payload=payload,
    )


class TimelineEventConsumer:
    """Consume evidence/timeline events through the tenant-scoped inbox."""

    EVENT_TYPES = frozenset({EventType.EVIDENCE_COLLECTED, EventType.TIMELINE_REBUILT})

    def __init__(
        self,
        *,
        consumer_name: str = "us1-timeline-events",
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
        return await self.dispatch(*args, **kwargs)

    async def handle(self, event: EventEnvelope, unit_of_work: PostgresUnitOfWork) -> None:
        if event.event_type not in self.EVENT_TYPES:
            raise EventContractError("timeline consumer received an unsupported event family")
        validate_payload_checksum(event)
        _validate_timeline_event(event)
        if self.handler is not None:
            result = self.handler(event, unit_of_work)
            if hasattr(result, "__await__"):
                await result


def _timeline_payload(event: TimelineEvent) -> dict[str, Any]:
    return {
        "tenant_id": event.tenant_id,
        "case_id": event.case_id,
        "timeline_event_id": event.timeline_event_id,
        "canonical_event_type": event.canonical_event_type,
        "source_event_ids": list(event.source_event_ids),
        "source_event_id": event.source_event_id,
        "source_identity": event.source_identity,
        "effective_at": event.effective_at.isoformat(),
        "observed_at": event.observed_at.isoformat(),
        "received_at": event.received_at.isoformat(),
        "ordering_key": event.ordering_key,
        "dedupe_key": event.dedupe_key,
        "event_payload": dict(event.event_payload),
        "evidence_references": list(event.evidence_references),
        "source_priority": event.source_priority,
        "conflicting_source_event_ids": list(event.conflicting_source_event_ids),
        "uncertainty_reasons": list(event.uncertainty_reasons),
    }


def _validate_timeline_event(event: EventEnvelope) -> None:
    payload = event.payload
    case_id = payload.get("case_id")
    if case_id != event.aggregate_id:
        raise EventContractError("timeline event case does not match envelope aggregate")
    if event.aggregate_type != "case":
        raise EventContractError("timeline event aggregate type is invalid")
    if event.event_type is EventType.EVIDENCE_COLLECTED:
        _require_text(payload, "evidence_id")
        _require_text(payload, "connector_id")
        _require_text(payload, "resource_type")
        return
    events = payload.get("events")
    if not isinstance(events, list):
        raise EventContractError("timeline.rebuilt events must be a list")
    for index, item in enumerate(events):
        if not isinstance(item, Mapping):
            raise EventContractError(f"timeline event {index} is not an object")
        if item.get("tenant_id") != event.tenant_id or item.get("case_id") != case_id:
            raise EventContractError("timeline event payload crosses tenant or case boundary")
        for name in (
            "timeline_event_id",
            "canonical_event_type",
            "source_event_id",
            "source_identity",
            "effective_at",
            "ordering_key",
            "dedupe_key",
        ):
            _require_text(item, name)


def _require_text(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise EventContractError(f"event payload {name} is required")
    return value


__all__ = [
    "TimelineEventConsumer",
    "build_evidence_collected_event",
    "build_timeline_rebuilt_event",
]
