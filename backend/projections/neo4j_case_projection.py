"""Tenant-scoped Neo4j case projection fed only by approved US1 events."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any

from app.auth.oidc import TenantAuthorizationContext
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.incident_events import EventContractError, validate_payload_checksum
from app.events.redpanda import DispatchResult, RedpandaInboxDispatcher
from packages.contracts.events import EventEnvelope, EventType

from .neo4j_projection import Neo4jDriver, ProjectionResult


class ProjectionEventError(EventContractError):
    """Raised when an event cannot be safely represented in the projection."""


class Neo4jCaseProjection:
    """Rebuildable write-only relationship projection.

    PostgreSQL-backed events are the input authority.  This adapter never reads or
    writes PostgreSQL business state and stores a per-event checkpoint in Neo4j only
    to make delivery/replay inspectionable; the PostgreSQL inbox remains the delivery
    idempotency boundary.
    """

    CONSUMER_NAME = "us1-neo4j-case-projection"
    SUPPORTED_EVENT_TYPES = frozenset(
        {
            EventType.INCIDENT_ACCEPTED,
            EventType.EVIDENCE_COLLECTED,
            EventType.TIMELINE_REBUILT,
        }
    )
    CONSTRAINTS = (
        "CREATE CONSTRAINT reclaim_case_identity IF NOT EXISTS "
        "FOR (case_node:ReclaimCase) REQUIRE (case_node.tenant_id, case_node.case_id) IS UNIQUE",
        "CREATE CONSTRAINT reclaim_incident_identity IF NOT EXISTS "
        "FOR (incident:ReclaimIncident) REQUIRE "
        "(incident.tenant_id, incident.incident_id) IS UNIQUE",
        "CREATE CONSTRAINT reclaim_evidence_identity IF NOT EXISTS "
        "FOR (evidence:ReclaimEvidence) REQUIRE "
        "(evidence.tenant_id, evidence.evidence_id) IS UNIQUE",
        "CREATE CONSTRAINT reclaim_timeline_identity IF NOT EXISTS "
        "FOR (timeline:ReclaimTimelineEvent) REQUIRE "
        "(timeline.tenant_id, timeline.timeline_event_id) IS UNIQUE",
        "CREATE CONSTRAINT reclaim_checkpoint_identity IF NOT EXISTS "
        "FOR (checkpoint:ReclaimProjectionCheckpoint) REQUIRE "
        "(checkpoint.tenant_id, checkpoint.consumer_name, checkpoint.event_id) IS UNIQUE",
    )
    CHECKPOINT = """
        MERGE (checkpoint:ReclaimProjectionCheckpoint {
            tenant_id: $tenant_id,
            consumer_name: $consumer_name,
            event_id: $event_id
        })
        ON CREATE SET checkpoint.payload_checksum = $payload_checksum,
                      checkpoint.occurred_at = $occurred_at
        WITH checkpoint
        WHERE checkpoint.payload_checksum = $payload_checksum
        RETURN checkpoint.event_id AS event_id
    """
    APPLY_INCIDENT = """
        MERGE (incident:ReclaimIncident {
            tenant_id: $tenant_id,
            incident_id: $incident_id
        })
        SET incident.source = $source,
            incident.received_at = $received_at,
            incident.correlation_id = $correlation_id
        MERGE (case_node:ReclaimCase {
            tenant_id: $tenant_id,
            case_id: $case_id
        })
        ON CREATE SET case_node.current_state = 'intake_received'
        SET case_node.correlation_id = $correlation_id
        MERGE (incident)-[:HAS_CASE]->(case_node)
        RETURN case_node.case_id AS case_id
    """
    APPLY_EVIDENCE = """
        MERGE (case_node:ReclaimCase {
            tenant_id: $tenant_id,
            case_id: $case_id
        })
        MERGE (evidence:ReclaimEvidence {
            tenant_id: $tenant_id,
            evidence_id: $evidence_id
        })
        SET evidence.connector_id = $connector_id,
            evidence.resource_type = $resource_type,
            evidence.source_identifier = $source_identifier,
            evidence.source_identity = $source_identity,
            evidence.observed_at = $observed_at,
            evidence.received_at = $received_at,
            evidence.raw_object_uri = $raw_object_uri,
            evidence.raw_checksum = $raw_checksum,
            evidence.completeness = $completeness,
            evidence.normalization_status = $normalization_status,
            evidence.integrity_status = $integrity_status,
            evidence.trust_classification = $trust_classification,
            evidence.collection_error = $collection_error
        MERGE (case_node)-[:HAS_EVIDENCE]->(evidence)
        FOREACH (fact IN $facts |
            MERGE (fact_node:ReclaimEvidenceFact {
                tenant_id: $tenant_id,
                evidence_id: $evidence_id,
                dedupe_key: fact.dedupe_key
            })
            SET fact_node.source_event_id = fact.source_event_id,
                fact_node.canonical_event_type = fact.canonical_event_type,
                fact_node.effective_at = fact.effective_at,
                fact_node.evidence_references = fact.evidence_references,
                fact_node.provider_identifiers = fact.provider_identifiers
            MERGE (evidence)-[:HAS_FACT]->(fact_node)
        )
        RETURN evidence.evidence_id AS evidence_id
    """
    APPLY_TIMELINE = """
        MERGE (case_node:ReclaimCase {
            tenant_id: $tenant_id,
            case_id: $case_id
        })
        SET case_node.current_state = $state,
            case_node.timeline_uncertainty = $uncertainty
        FOREACH (timeline IN $events |
            MERGE (timeline_node:ReclaimTimelineEvent {
                tenant_id: $tenant_id,
                timeline_event_id: timeline.timeline_event_id
            })
            SET timeline_node.canonical_event_type = timeline.canonical_event_type,
                timeline_node.source_event_ids = timeline.source_event_ids,
                timeline_node.source_event_id = timeline.source_event_id,
                timeline_node.source_identity = timeline.source_identity,
                timeline_node.effective_at = timeline.effective_at,
                timeline_node.observed_at = timeline.observed_at,
                timeline_node.received_at = timeline.received_at,
                timeline_node.ordering_key = timeline.ordering_key,
                timeline_node.dedupe_key = timeline.dedupe_key,
                timeline_node.event_payload = timeline.event_payload,
                timeline_node.evidence_references = timeline.evidence_references,
                timeline_node.source_priority = timeline.source_priority,
                timeline_node.conflicting_source_event_ids = timeline.conflicting_source_event_ids,
                timeline_node.uncertainty_reasons = timeline.uncertainty_reasons
            MERGE (case_node)-[:HAS_TIMELINE_EVENT]->(timeline_node)
        )
        RETURN case_node.case_id AS case_id
    """
    RESET_TENANT = """
        MATCH (node)
        WHERE node.tenant_id = $tenant_id
        DETACH DELETE node
    """
    CHECKPOINTS_FOR_TENANT = """
        MATCH (checkpoint:ReclaimProjectionCheckpoint)
        WHERE checkpoint.tenant_id = $tenant_id
        RETURN checkpoint.consumer_name AS consumer_name,
               checkpoint.event_id AS event_id,
               checkpoint.payload_checksum AS payload_checksum
        ORDER BY checkpoint.event_id
    """

    def __init__(self, driver: Neo4jDriver, *, database: str | None = None) -> None:
        self.driver = driver
        self.database = database

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        username: str,
        password: str,
        database: str | None = None,
    ) -> Neo4jCaseProjection:
        from neo4j import GraphDatabase

        return cls(
            GraphDatabase.driver(uri, auth=(username, password)),
            database=database,
        )

    def bootstrap(self) -> None:
        with self._session() as session:
            for query in self.CONSTRAINTS:
                session.run(query).consume()

    def apply(
        self,
        event: EventEnvelope,
        *,
        consumer_name: str = CONSUMER_NAME,
    ) -> str:
        """Apply one approved event and its projection checkpoint idempotently."""

        if not consumer_name.strip():
            raise ValueError("projection consumer_name is required")
        if event.event_type not in self.SUPPORTED_EVENT_TYPES:
            raise ProjectionEventError(
                f"event type {event.event_type.value!r} is outside the US1 projection"
            )
        normalized = _validate_projection_event(event)
        with self._session() as session:
            execute_write = getattr(session, "execute_write", None)
            if execute_write is not None:
                result = execute_write(
                    lambda transaction: self._apply_transaction(
                        transaction,
                        event,
                        normalized,
                        consumer_name,
                    )
                )
            else:
                result = self._apply_transaction(session, event, normalized, consumer_name)
        return str(result)

    def reset_tenant(self, tenant_id: str) -> int:
        if not tenant_id.strip():
            raise ValueError("tenant_id is required")
        with self._session() as session:
            result = session.run(self.RESET_TENANT, tenant_id=tenant_id).consume()
        counters = getattr(result, "counters", None)
        return int(getattr(counters, "nodes_deleted", 0))

    def rebuild(
        self,
        tenant_id: str,
        events: Iterable[EventEnvelope],
        *,
        consumer_name: str = CONSUMER_NAME,
    ) -> ProjectionResult:
        """Reset one tenant and replay only same-tenant authoritative events."""

        input_events = tuple(events)
        if any(event.tenant_id != tenant_id for event in input_events):
            raise ProjectionEventError("projection rebuild input crossed tenant boundary")
        for event in input_events:
            if event.event_type not in self.SUPPORTED_EVENT_TYPES:
                raise ProjectionEventError("projection rebuild contains an unsupported event")
            _validate_projection_event(event)
        ordered = tuple(sorted(input_events, key=lambda event: (event.occurred_at, event.event_id)))
        deleted = self.reset_tenant(tenant_id)
        for event in ordered:
            self.apply(event, consumer_name=consumer_name)
        return ProjectionResult(tenant_id, len(ordered), deleted)

    def checkpoints(self, tenant_id: str) -> tuple[dict[str, str], ...]:
        """Return non-authoritative checkpoint metadata for operator inspection."""

        if not tenant_id.strip():
            raise ValueError("tenant_id is required")
        with self._session() as session:
            result = session.run(self.CHECKPOINTS_FOR_TENANT, tenant_id=tenant_id)
            records = result.data() if hasattr(result, "data") else result
        return tuple(dict(record) for record in records)

    def close(self) -> None:
        self.driver.close()

    def _apply_transaction(
        self,
        transaction: Any,
        event: EventEnvelope,
        normalized: Mapping[str, Any],
        consumer_name: str,
    ) -> str:
        checkpoint = transaction.run(
            self.CHECKPOINT,
            tenant_id=event.tenant_id,
            consumer_name=consumer_name,
            event_id=event.event_id,
            payload_checksum=event.payload_checksum,
            occurred_at=event.occurred_at.isoformat(),
        ).single()
        if checkpoint is None:
            raise ProjectionEventError("projection checkpoint checksum conflict")

        if event.event_type is EventType.INCIDENT_ACCEPTED:
            query = self.APPLY_INCIDENT
        elif event.event_type is EventType.EVIDENCE_COLLECTED:
            query = self.APPLY_EVIDENCE
        else:
            query = self.APPLY_TIMELINE
        result = transaction.run(query, **normalized).single()
        if result is None:
            raise ProjectionEventError("projection write returned no identity")
        identity_name = (
            "evidence_id" if event.event_type is EventType.EVIDENCE_COLLECTED else "case_id"
        )
        return str(result[identity_name] if isinstance(result, Mapping) else result[0])

    def _session(self) -> Any:
        if self.database is None:
            return self.driver.session()
        return self.driver.session(database=self.database)


class Neo4jCaseProjectionConsumer:
    """Redpanda consumer that commits delivery only after Neo4j projection handling."""

    def __init__(
        self,
        projection: Neo4jCaseProjection,
        *,
        consumer_name: str = Neo4jCaseProjection.CONSUMER_NAME,
    ) -> None:
        self.projection = projection
        self.consumer_name = consumer_name
        self._dispatcher = RedpandaInboxDispatcher(consumer_name=consumer_name)

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
        del unit_of_work
        if event.event_type in Neo4jCaseProjection.SUPPORTED_EVENT_TYPES:
            self.projection.apply(event, consumer_name=self.consumer_name)
        elif event.event_type not in set(EventType):
            raise ProjectionEventError("projection received an unknown event type")
        # Known event families outside the case/evidence/timeline projection are
        # acknowledged by this consumer without creating graph data.


def _validate_projection_event(event: EventEnvelope) -> dict[str, Any]:
    try:
        validate_payload_checksum(event)
    except EventContractError as exc:
        raise ProjectionEventError(str(exc)) from exc
    payload = event.payload
    payload_tenant = payload.get("tenant_id")
    if payload_tenant is not None and payload_tenant != event.tenant_id:
        raise ProjectionEventError("projection payload crosses tenant boundary")
    if event.event_type is EventType.INCIDENT_ACCEPTED:
        if event.aggregate_type != "incident":
            raise ProjectionEventError("incident.accepted aggregate type is invalid")
        incident_id = _required_text(payload, "incident_id")
        if incident_id != event.aggregate_id:
            raise ProjectionEventError("incident identity does not match envelope")
        return {
            "tenant_id": event.tenant_id,
            "incident_id": incident_id,
            "case_id": _required_text(payload, "case_id"),
            "source": _required_text(payload, "source"),
            "received_at": _required_text(payload, "received_at"),
            "correlation_id": event.correlation_id,
        }
    if event.aggregate_type != "case":
        raise ProjectionEventError("case projection aggregate type is invalid")
    case_id = _required_text(payload, "case_id")
    if case_id != event.aggregate_id:
        raise ProjectionEventError("case identity does not match envelope")
    if event.event_type is EventType.EVIDENCE_COLLECTED:
        return {
            "tenant_id": event.tenant_id,
            "case_id": case_id,
            "evidence_id": _required_text(payload, "evidence_id"),
            "connector_id": _required_text(payload, "connector_id"),
            "resource_type": _required_text(payload, "resource_type"),
            "source_identifier": _required_text(payload, "source_identifier"),
            "source_identity": _required_text(payload, "source_identity"),
            "observed_at": _required_text(payload, "observed_at"),
            "received_at": _required_text(payload, "received_at"),
            "raw_object_uri": payload.get("raw_object_uri"),
            "raw_checksum": _required_text(payload, "raw_checksum"),
            "completeness": _required_text(payload, "completeness"),
            "normalization_status": _required_text(payload, "normalization_status"),
            "integrity_status": _required_text(payload, "integrity_status"),
            "trust_classification": _required_text(payload, "trust_classification"),
            "collection_error": payload.get("collection_error"),
            "facts": _fact_payload(payload.get("normalized_facts", [])),
        }
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise ProjectionEventError("timeline.rebuilt events must be a list")
    return {
        "tenant_id": event.tenant_id,
        "case_id": case_id,
        "state": _required_text(payload, "state"),
        "uncertainty": _string_list(payload.get("uncertainty", []), "uncertainty"),
        "events": _timeline_payload(raw_events, event.tenant_id, case_id),
    }


def _fact_payload(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ProjectionEventError("evidence normalized_facts must be a list")
    facts: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ProjectionEventError("evidence fact is not an object")
        facts.append(
            {
                "source_event_id": _required_text(item, "source_event_id"),
                "canonical_event_type": _required_text(item, "canonical_event_type"),
                "dedupe_key": _required_text(item, "dedupe_key"),
                "effective_at": _required_text(item, "effective_at"),
                "evidence_references": _string_list(
                    item.get("evidence_references", []), "evidence_references"
                ),
                "provider_identifiers": _canonical_json(
                    _string_map(item.get("provider_identifiers", {}), "provider_identifiers")
                ),
            }
        )
    return facts


def _timeline_payload(value: list[object], tenant_id: str, case_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ProjectionEventError("timeline payload item is not an object")
        if item.get("tenant_id") != tenant_id or item.get("case_id") != case_id:
            raise ProjectionEventError("timeline payload crosses tenant or case boundary")
        events.append(
            {
                "timeline_event_id": _required_text(item, "timeline_event_id"),
                "canonical_event_type": _required_text(item, "canonical_event_type"),
                "source_event_ids": _string_list(
                    item.get("source_event_ids", []), "source_event_ids"
                ),
                "source_event_id": _required_text(item, "source_event_id"),
                "source_identity": _required_text(item, "source_identity"),
                "effective_at": _required_text(item, "effective_at"),
                "observed_at": _required_text(item, "observed_at"),
                "received_at": _required_text(item, "received_at"),
                "ordering_key": _required_text(item, "ordering_key"),
                "dedupe_key": _required_text(item, "dedupe_key"),
                "event_payload": _canonical_json(
                    _mapping(item.get("event_payload", {}), "event_payload")
                ),
                "evidence_references": _string_list(
                    item.get("evidence_references", []), "evidence_references"
                ),
                "source_priority": _nonnegative_int(item.get("source_priority", 100)),
                "conflicting_source_event_ids": _string_list(
                    item.get("conflicting_source_event_ids", []),
                    "conflicting_source_event_ids",
                ),
                "uncertainty_reasons": _string_list(
                    item.get("uncertainty_reasons", []), "uncertainty_reasons"
                ),
            }
        )
    return events


def _required_text(value: Mapping[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise ProjectionEventError(f"projection payload {name} is required")
    return item


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ProjectionEventError(f"projection payload {name} must be a string list")
    return list(value)


def _string_map(value: object, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not key.strip() or not isinstance(item, str) or not item.strip()
        for key, item in value.items()
    ):
        raise ProjectionEventError(f"projection payload {name} must be a string map")
    return dict(value)


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectionEventError(f"projection payload {name} must be an object")
    return dict(value)


def _nonnegative_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectionEventError("projection source_priority must be non-negative")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "Neo4jCaseProjection",
    "Neo4jCaseProjectionConsumer",
    "ProjectionEventError",
]
