"""Tests for the production persisted-evidence Temporal timeline activity."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Self

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.storage.minio_evidence import ImmutableEvidenceStore
from evidence.storage import EvidenceStorage, InMemoryObjectStorage
from temporalio.exceptions import ApplicationError
from timeline.reconstruct import TimelineReconstructor
from workflows.activities.timeline import (
    TimelineActivityDependencies,
    make_timeline_activities,
)
from workflows.commands import CaseWorkflowCommand


def context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="workflow-worker",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


class EvidenceRepository:
    def __init__(self, row: tuple[object, ...]) -> None:
        self.row = row

    def for_case(self, *, case_id: str) -> list[tuple[object, ...]]:
        return [self.row] if self.row[2] == case_id else []


class TimelineRepository:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def upsert(self, **values: object) -> object:
        self.rows.append(values)
        return values


class Cases:
    def __init__(self) -> None:
        self.states: list[str] = []
        self.uncertainty: tuple[str, ...] | None = None

    def set_timeline_uncertainty(
        self, *, case_id: str, uncertainty: tuple[str, ...]
    ) -> object:
        self.uncertainty = uncertainty
        return ("tenant-a", case_id, "incident-1", "uncertainty-updated")

    def transition_state(self, *, case_id: str, new_state: str) -> object:
        self.states.append(new_state)
        return ("tenant-a", case_id, "incident-1", new_state)


class Outbox:
    def __init__(self) -> None:
        self.events: list[object] = []

    def enqueue(self, *, outbox_id: str, event: object) -> object:
        self.events.append(event)
        return event


class UnitOfWork:
    def __init__(self, row: tuple[object, ...]) -> None:
        self.evidence = EvidenceRepository(row)
        self.timeline = TimelineRepository()
        self.cases = Cases()
        self.outbox = Outbox()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


def command() -> CaseWorkflowCommand:
    return CaseWorkflowCommand(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        command_id="command-1",
        stages=("rebuild_timeline",),
    )


def activity_and_state() -> tuple[Any, UnitOfWork, ImmutableEvidenceStore]:
    storage = ImmutableEvidenceStore(InMemoryObjectStorage())
    payload = json.dumps(
        {
            "schema_version": "1.0.0",
            "mode": "replay",
            "seed": "timeline-activity-test",
            "provenance": {"source": "test-fixture", "version": "1.0.0"},
            "source_identity": "merchant-session-store",
            "connector_status": "complete",
            "normalized_facts": [
                {
                    "source_event_id": "session-event-1",
                    "canonical_event_type": "session.opened",
                    "dedupe_key": "session:session-1",
                    "event_at": "2026-08-30T09:00:00Z",
                    "source_priority": 100,
                    "session_id": "session-1",
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    stored = storage.put(
        tenant_id="tenant-a",
        object_name="case-1/raw/sessions/evidence-1.json",
        content=payload,
    )
    observed_at = datetime(2026, 8, 30, 9, tzinfo=UTC)
    row = (
        "tenant-a",
        "evidence-1",
        "case-1",
        "sim-sessions",
        "sessions",
        "session-event-1",
        observed_at,
        observed_at + timedelta(minutes=1),
        f"minio://{stored.bucket}/{stored.object_name}",
        stored.checksum,
        "normalized",
        "complete",
        "untrusted",
        None,
    )
    unit_of_work = UnitOfWork(row)

    def factory(_context: Any) -> UnitOfWork:
        return unit_of_work

    activity = make_timeline_activities(
        TimelineActivityDependencies(
            reconstructor=TimelineReconstructor(unit_of_work_factory=factory),
            evidence_storage=EvidenceStorage(storage),
            unit_of_work_factory=factory,
            authorization_context_factory=context,
        )
    )
    return activity, unit_of_work, storage


@pytest.mark.asyncio
async def test_timeline_activity_rebuilds_from_persisted_raw_evidence() -> None:
    activity, unit_of_work, _ = activity_and_state()

    result = await activity.rebuild_timeline(command())

    assert result["authoritative"] is True
    assert result["timeline_event_count"] == 1
    assert unit_of_work.timeline.rows[0]["dedupe_key"] == "session:session-1"
    assert unit_of_work.cases.states == ["timeline_ready"]
    assert len(unit_of_work.outbox.events) == 1


@pytest.mark.asyncio
async def test_timeline_activity_rejects_raw_evidence_from_another_tenant() -> None:
    activity, unit_of_work, storage = activity_and_state()
    stored = storage.put(
        tenant_id="tenant-b",
        object_name="case-1/raw/sessions/evidence-foreign.json",
        content=b"{}",
    )
    unit_of_work.evidence.row = (
        *unit_of_work.evidence.row[:8],
        f"minio://{stored.bucket}/{stored.object_name}",
        stored.checksum,
        *unit_of_work.evidence.row[10:],
    )

    with pytest.raises(ApplicationError, match="tenant") as error:
        await activity.rebuild_timeline(command())

    assert error.value.non_retryable is True
