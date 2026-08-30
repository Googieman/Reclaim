"""Neo4j relationship projection rebuilt from authoritative domain events."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from packages.contracts.events import EventEnvelope


class Neo4jSession(Protocol):
    def run(self, query: str, **parameters: Any) -> Any: ...


class Neo4jDriver(Protocol):
    def session(self, **kwargs: Any) -> Any: ...

    def close(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    tenant_id: str
    applied_events: int
    deleted_nodes: int = 0


class Neo4jProjection:
    """Write-only projection adapter with no PostgreSQL or business-state methods."""

    EVENT_CONSTRAINT = (
        "CREATE CONSTRAINT reclaim_event_identity IF NOT EXISTS "
        "FOR (event:ReclaimEvent) REQUIRE (event.tenant_id, event.event_id) IS UNIQUE"
    )
    APPLY_EVENT = """
        MERGE (aggregate:ReclaimAggregate {
            tenant_id: $tenant_id,
            aggregate_type: $aggregate_type,
            aggregate_id: $aggregate_id
        })
        MERGE (event:ReclaimEvent {tenant_id: $tenant_id, event_id: $event_id})
        SET event.event_type = $event_type,
            event.schema_version = $schema_version,
            event.occurred_at = $occurred_at,
            event.correlation_id = $correlation_id,
            event.payload_checksum = $payload_checksum
        MERGE (aggregate)-[:HAS_EVENT]->(event)
        RETURN event.event_id AS event_id
    """
    RESET_TENANT = """
        MATCH (node)
        WHERE node.tenant_id = $tenant_id
        DETACH DELETE node
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
    ) -> Neo4jProjection:
        from neo4j import GraphDatabase

        return cls(
            GraphDatabase.driver(uri, auth=(username, password)),
            database=database,
        )

    def bootstrap(self) -> None:
        with self._session() as session:
            session.run(self.EVENT_CONSTRAINT).consume()

    def apply(self, event: EventEnvelope) -> str:
        """Project one event idempotently; duplicate event IDs only update the projection."""

        with self._session() as session:
            result = session.run(
                self.APPLY_EVENT,
                tenant_id=event.tenant_id,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                event_id=event.event_id,
                event_type=event.event_type.value,
                schema_version=event.schema_version,
                occurred_at=event.occurred_at.isoformat(),
                correlation_id=event.correlation_id,
                payload_checksum=event.payload_checksum,
            ).single()
        if result is None:
            raise RuntimeError("Neo4j projection did not return an event identity")
        return str(result["event_id"] if isinstance(result, dict) else result[0])

    def reset_tenant(self, tenant_id: str) -> int:
        if not tenant_id.strip():
            raise ValueError("tenant_id is required")
        with self._session() as session:
            result = session.run(self.RESET_TENANT, tenant_id=tenant_id).consume()
        counters = getattr(result, "counters", None)
        return int(getattr(counters, "nodes_deleted", 0))

    def rebuild(self, tenant_id: str, events: Iterable[EventEnvelope]) -> ProjectionResult:
        """Delete and recreate one tenant projection from caller-supplied authoritative events."""

        input_events = tuple(events)
        if any(event.tenant_id != tenant_id for event in input_events):
            raise ValueError("projection rebuild input crossed tenant boundary")
        scoped_events = sorted(
            input_events,
            key=lambda event: (event.occurred_at, event.event_id),
        )
        deleted = self.reset_tenant(tenant_id)
        for event in scoped_events:
            self.apply(event)
        return ProjectionResult(tenant_id, len(scoped_events), deleted)

    def close(self) -> None:
        self.driver.close()

    def _session(self) -> Any:
        if self.database is None:
            return self.driver.session()
        return self.driver.session(database=self.database)
