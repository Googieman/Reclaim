"""T057 rebuildable Neo4j case/evidence/timeline projection coverage."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.incident_events import build_incident_accepted_event
from app.events.redpanda import EventTransportError
from app.events.redpanda import serialize_event
from app.events.timeline_events import (
    build_evidence_collected_event,
    build_timeline_rebuilt_event,
)
from evidence.models import CollectedEvidence
from projections.neo4j_case_projection import (
    Neo4jCaseProjection,
    Neo4jCaseProjectionConsumer,
    ProjectionEventError,
)
from timeline.models import TimelineEvent, TimelineRebuildResult

from backend.tests.integration.support import (
    RecordingDatabase,
    make_authorization_context,
)


NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


class FakeResult:
    def __init__(
        self,
        record: dict[str, object] | None = None,
        records: list[dict[str, object]] | None = None,
    ) -> None:
        self.record = record
        self.records = records

    def single(self) -> dict[str, object] | None:
        return self.record

    def consume(self) -> SimpleNamespace:
        return SimpleNamespace(counters=SimpleNamespace(nodes_deleted=3))

    def data(self) -> list[dict[str, object]]:
        if self.records is not None:
            return self.records
        return [] if self.record is None else [self.record]


class FakeTransaction:
    def __init__(
        self,
        queries: list[tuple[str, dict[str, object]]],
        checkpoints: set[str],
    ) -> None:
        self.queries = queries
        self.checkpoints = checkpoints

    def run(self, query: str, **parameters: object) -> FakeResult:
        self.queries.append((query, parameters))
        if "RETURN checkpoint.event_id AS event_id" in query:
            self.checkpoints.add(str(parameters["event_id"]))
            return FakeResult({"event_id": parameters["event_id"]})
        if "RETURN evidence.evidence_id AS evidence_id" in query:
            return FakeResult({"evidence_id": parameters["evidence_id"]})
        return FakeResult({"case_id": parameters.get("case_id", "case-1")})


class FakeSession:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict[str, object]]] = []
        self.checkpoints: set[str] = set()

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback

    def run(self, query: str, **parameters: object) -> FakeResult:
        self.queries.append((query, parameters))
        if "RETURN checkpoint.consumer_name" in query:
            return FakeResult(
                records=[
                    {
                        "consumer_name": "us1-neo4j-case-projection",
                        "event_id": event_id,
                        "payload_checksum": "checksum-1",
                    }
                    for event_id in sorted(self.checkpoints)
                ]
            )
        if "RETURN evidence.evidence_id AS evidence_id" in query:
            return FakeResult({"evidence_id": parameters["evidence_id"]})
        return FakeResult()

    def execute_write(self, callback: Any) -> object:
        return callback(FakeTransaction(self.queries, self.checkpoints))


class FakeDriver:
    def __init__(self) -> None:
        self.session_instance = FakeSession()
        self.closed = False

    def session(self, **kwargs: object) -> FakeSession:
        del kwargs
        return self.session_instance

    def close(self) -> None:
        self.closed = True


def events(tenant_id: str = "tenant-a", *, uncertain: bool = False) -> tuple[Any, ...]:
    incident = build_incident_accepted_event(
        tenant_id=tenant_id,
        correlation_id="corr-1",
        incident_id="incident-1",
        case_id="case-1",
        source="operator",
        received_at=NOW,
        report_reference=None,
        report_content_present=True,
        causation_id="intake-1",
        producer="intake-api@1.0.0",
    )
    evidence = CollectedEvidence(
        tenant_id=tenant_id,
        case_id="case-1",
        correlation_id="corr-1",
        evidence_id="evidence-1",
        connector_id="sim-sessions",
        resource_type="sessions",
        source_identifier="session-event-1",
        source_identity="merchant-sessions",
        observed_at=NOW,
        received_at=NOW,
        raw_object_uri=f"minio://reclaim/{tenant_id}/evidence-1",
        raw_checksum="sha256:raw-1",
        expected_checksum="sha256:raw-1",
        completeness="complete",
        normalization_status="normalized",
        integrity_status="verified",
    )
    evidence_event = build_evidence_collected_event(evidence)
    timeline = TimelineEvent(
        tenant_id=tenant_id,
        case_id="case-1",
        timeline_event_id="timeline-1",
        canonical_event_type="session.opened",
        source_event_ids=("session-event-1",),
        source_event_id="session-event-1",
        source_identity="merchant-sessions",
        effective_at=NOW + timedelta(minutes=1),
        observed_at=NOW,
        received_at=NOW,
        ordering_key="2026-08-30T10:01:00+00:00|session.opened|merchant-sessions|session-event-1",
        dedupe_key="session:session-1",
        event_payload={"state": "observed"},
        evidence_references=("evidence-1",),
        conflicting_source_event_ids=("fallback-1",) if uncertain else (),
        uncertainty_reasons=("conflicting_sources",) if uncertain else (),
    )
    timeline_event = build_timeline_rebuilt_event(
        TimelineRebuildResult(
            tenant_id=tenant_id,
            case_id="case-1",
            events=(timeline,),
            uncertainty=("session:s-1:conflicting_sources",) if uncertain else (),
        ),
        correlation_id="corr-1",
    )
    return incident, evidence_event, timeline_event


def test_case_projection_applies_three_us1_families_and_is_replay_idempotent() -> None:
    driver = FakeDriver()
    projection = Neo4jCaseProjection(driver)
    projection.bootstrap()
    incident, evidence, timeline = events()

    assert projection.apply(incident) == "case-1"
    assert projection.apply(evidence) == "evidence-1"
    assert projection.apply(timeline) == "case-1"
    assert projection.apply(evidence) == "evidence-1"
    assert len(projection.checkpoints("tenant-a")) == 3

    result = projection.rebuild("tenant-a", (timeline, evidence, incident))
    assert result.applied_events == 3
    assert result.deleted_nodes == 3
    assert any("HAS_EVIDENCE" in query for query, _ in driver.session_instance.queries)
    assert any(
        "HAS_TIMELINE_EVENT" in query for query, _ in driver.session_instance.queries
    )


def test_projection_rejects_cross_tenant_and_poisoned_payloads() -> None:
    projection = Neo4jCaseProjection(FakeDriver())
    incident, _, _ = events()
    with pytest.raises(ProjectionEventError, match="tenant boundary"):
        projection.rebuild(
            "tenant-a", (incident.model_copy(update={"tenant_id": "tenant-b"}),)
        )

    poisoned = incident.model_copy(
        update={"payload": {"incident_id": "attacker-controlled"}}
    )
    with pytest.raises(ProjectionEventError, match="checksum"):
        projection.apply(poisoned)


def test_projection_preserves_case_and_event_uncertainty() -> None:
    driver = FakeDriver()
    projection = Neo4jCaseProjection(driver)
    timeline = events(uncertain=True)[2]

    assert projection.apply(timeline) == "case-1"
    timeline_query = next(
        parameters
        for query, parameters in driver.session_instance.queries
        if "HAS_TIMELINE_EVENT" in query
    )
    assert timeline_query["uncertainty"] == ["session:s-1:conflicting_sources"]
    assert timeline_query["events"][0]["conflicting_source_event_ids"] == ["fallback-1"]
    assert timeline_query["events"][0]["uncertainty_reasons"] == ["conflicting_sources"]


@pytest.mark.asyncio
async def test_projection_consumer_uses_postgres_inbox_and_reset_cannot_change_postgres_truth() -> (
    None
):
    driver = FakeDriver()
    projection = Neo4jCaseProjection(driver)
    consumer = Neo4jCaseProjectionConsumer(projection)
    database = RecordingDatabase()

    def factory(context: Any) -> PostgresUnitOfWork:
        return PostgresUnitOfWork(database.connect, authorization_context=context)

    incident, _, _ = events()
    database.seed_outbox(incident)

    first = await consumer.dispatch(
        serialize_event(incident),
        unit_of_work_factory=factory,
        authorization_context=make_authorization_context(),
    )
    duplicate = await consumer.dispatch(
        serialize_event(incident),
        unit_of_work_factory=factory,
        authorization_context=make_authorization_context(),
    )
    assert first.processed is True
    assert duplicate.processed is False
    assert (
        database.inbox[("tenant-a", consumer.consumer_name, incident.event_id)][6]
        == "handled"
    )

    projection.reset_tenant("tenant-a")
    assert (
        database.inbox[("tenant-a", consumer.consumer_name, incident.event_id)][6]
        == "handled"
    )

    with pytest.raises(EventTransportError, match="tenant"):
        await consumer.dispatch(
            serialize_event(incident),
            unit_of_work_factory=factory,
            authorization_context=make_authorization_context("tenant-b"),
        )


@pytest.mark.skipif(
    not (
        os.getenv("RECLAIM_NEO4J_URI")
        and os.getenv("RECLAIM_NEO4J_USER")
        and os.getenv("RECLAIM_NEO4J_PASSWORD")
    ),
    reason="Neo4j URI and credentials are required for live validation",
)
def test_live_case_projection_rebuild_and_reset_if_configured() -> None:
    tenant_id = f"t057-live-{uuid4().hex[:12]}"
    scoped_events = events(tenant_id)
    projection = Neo4jCaseProjection.from_uri(
        os.environ["RECLAIM_NEO4J_URI"],
        username=os.environ["RECLAIM_NEO4J_USER"],
        password=os.environ["RECLAIM_NEO4J_PASSWORD"],
    )
    try:
        projection.bootstrap()
        first = projection.rebuild(tenant_id, scoped_events)
        assert first.applied_events == 3
        reset_deleted = projection.reset_tenant(tenant_id)
        assert reset_deleted >= 1
        second = projection.rebuild(tenant_id, scoped_events)
        assert second.applied_events == 3
    finally:
        projection.reset_tenant(tenant_id)
        projection.close()
