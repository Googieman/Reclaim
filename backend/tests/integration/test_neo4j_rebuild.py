"""Rebuildability tests for the Neo4j projection boundary."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from projections.neo4j_projection import Neo4jProjection

from .support import make_event


class FakeSession:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict[str, object]]] = []

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None

    def run(self, query: str, **parameters: object) -> object:
        self.queries.append((query, parameters))
        if "MERGE (event" in query:
            return SimpleNamespace(single=lambda: {"event_id": parameters["event_id"]})
        return SimpleNamespace(
            consume=lambda: SimpleNamespace(counters=SimpleNamespace(nodes_deleted=2))
        )


class FakeDriver:
    def __init__(self) -> None:
        self.session_instance = FakeSession()
        self.closed = False

    def session(self, **kwargs: object) -> FakeSession:
        return self.session_instance

    def close(self) -> None:
        self.closed = True


def test_projection_applies_and_rebuilds_only_tenant_events() -> None:
    driver = FakeDriver()
    projection = Neo4jProjection(driver)
    first = make_event(event_id="event-2")
    second = make_event(event_id="event-1")

    assert projection.apply(first) == "event-2"
    result = projection.rebuild("tenant-a", [first, second])

    assert result.applied_events == 2
    assert result.deleted_nodes == 2
    assert any("DETACH DELETE" in query for query, _ in driver.session_instance.queries)


def test_projection_rejects_cross_tenant_rebuild_input() -> None:
    projection = Neo4jProjection(FakeDriver())
    with pytest.raises(ValueError, match="tenant boundary"):
        projection.rebuild("tenant-a", [make_event(), make_event(tenant_id="tenant-b")])


def test_live_neo4j_projection_if_service_is_configured() -> None:
    uri = os.getenv("RECLAIM_NEO4J_URI")
    username = os.getenv("RECLAIM_NEO4J_USER")
    password = os.getenv("RECLAIM_NEO4J_PASSWORD")
    if not (uri and username and password):
        pytest.skip("Neo4j URI and credentials are required for live validation")
    event = make_event(event_id="neo4j-live-test")
    projection = Neo4jProjection.from_uri(uri, username=username, password=password)
    try:
        projection.bootstrap()
        result = projection.rebuild(event.tenant_id, [event])
        assert result.applied_events == 1
    finally:
        projection.close()
