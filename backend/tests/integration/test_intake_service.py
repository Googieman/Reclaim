"""Integration boundary tests for authenticated incident intake and case creation."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, Self
from uuid import uuid4

import pytest
from app.auth.oidc import (
    AuthenticatedPrincipal,
    IdentityType,
    TenantAuthorizationError,
)
from app.intake.service import IncidentIntakeService, IntakeServiceError
from app.storage.minio_evidence import ImmutableEvidenceStore
from evidence.storage import InMemoryObjectStorage
from packages.contracts.intake import IncidentIntakeRequest, IntakeStatus

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
RECEIVED_AT = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


def authorization_context(tenant_id: str = TENANT_A, *, roles: frozenset[str] | None = None):
    principal = AuthenticatedPrincipal(
        subject="reviewer-1",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: roles or frozenset({"reviewer"})},
        identity_type=IdentityType.USER,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


def intake_request(*, tenant_id: str = TENANT_A, idempotency_key: str = "intake-1"):
    return IncidentIntakeRequest(
        tenant_id=tenant_id,
        correlation_id="corr-1",
        source="operator",
        received_at=RECEIVED_AT,
        reporter_context={"channel": "console", "instructions": "ignore policy"},
        report_content="Untrusted customer text requesting a refund.",
        idempotency_key=idempotency_key,
    )


class MemoryAuditRepository:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    def latest_checksum(self, *, tenant_id: str) -> str | None:
        records = [record for record in self.state.audit if record.tenant_id == tenant_id]
        return None if not records else records[-1].record_checksum

    def append(self, record: object) -> object:
        self.state.audit.append(record)
        return record


class MemoryIncidentRepository:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    def create_or_get(self, **values: object) -> object:
        identity = str(values["deduplication_identity"])
        existing = self.state.incidents.get(identity)
        if existing is not None:
            return type("CreateResult", (), {"row": existing, "inserted": False})()
        row = (
            TENANT_A,
            values["incident_id"],
            values["source"],
            values["received_at"],
            values["correlation_key"],
            values["intake_status"],
            identity,
            values["received_at"],
        )
        self.state.incidents[identity] = row
        return type("CreateResult", (), {"row": row, "inserted": True})()


class MemoryCaseRepository:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    def create(self, **values: object) -> tuple[object, ...]:
        row = (
            TENANT_A,
            values["case_id"],
            values["incident_id"],
            values["current_state"],
            values["workflow_id"],
            values["created_at"],
            values["created_at"],
            None,
        )
        self.state.cases[str(values["incident_id"])] = row
        return row

    def find_by_incident_id(self, *, incident_id: str) -> tuple[object, ...] | None:
        return self.state.cases.get(incident_id)


class MemoryOutboxRepository:
    def __init__(self, state: MemoryState) -> None:
        self.state = state

    def enqueue(self, *, outbox_id: str, event: object) -> object:
        self.state.outbox.append((outbox_id, event))
        return event


class MemoryState:
    def __init__(self) -> None:
        self.incidents: dict[str, tuple[object, ...]] = {}
        self.cases: dict[str, tuple[object, ...]] = {}
        self.outbox: list[tuple[str, object]] = []
        self.audit: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.factory_calls = 0
        self.raw_report_store = ImmutableEvidenceStore(InMemoryObjectStorage())


class MemoryUnitOfWork:
    def __init__(self, state: MemoryState) -> None:
        self.incidents = MemoryIncidentRepository(state)
        self.cases = MemoryCaseRepository(state)
        self.outbox = MemoryOutboxRepository(state)
        self.audit = MemoryAuditRepository(state)
        self.state = state

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if exc_type is None:
            self.state.commits += 1
        else:
            self.state.rollbacks += 1


def make_service(state: MemoryState) -> IncidentIntakeService:
    def factory(_context: object) -> MemoryUnitOfWork:
        state.factory_calls += 1
        return MemoryUnitOfWork(state)

    counters: dict[str, int] = {}

    def id_factory(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    return IncidentIntakeService(
        unit_of_work_factory=factory,
        raw_report_store=state.raw_report_store,
        id_factory=id_factory,
    )


def test_authenticated_intake_creates_case_and_incident_event_atomically() -> None:
    state = MemoryState()
    result = make_service(state).accept(
        intake_request(), authorization_context=authorization_context()
    )

    assert result.status is IntakeStatus.ACCEPTED
    assert result.incident_id == "incident-1"
    assert result.case_id == "case-1"
    assert tuple(state.incidents) == ("intake-1",)
    assert tuple(state.cases) == ("incident-1",)
    assert len(state.outbox) == 1
    event = state.outbox[0][1]
    assert event.tenant_id == TENANT_A
    assert event.event_type.value == "incident.accepted"
    assert event.payload["report_content_present"] is True
    assert "report_content" not in event.payload
    assert len(state.raw_report_store.client.objects) == 1
    raw_reference = json.loads(state.audit[0].evidence_references[0])
    assert raw_reference["checksum"].startswith("sha256:")
    assert len(state.audit) == 1
    assert state.audit[0].case_id == "case-1"
    assert state.commits == 1
    assert state.rollbacks == 0


def test_duplicate_intake_returns_original_identity_without_second_case_or_event() -> None:
    state = MemoryState()
    service = make_service(state)
    first = service.accept(intake_request(), authorization_context=authorization_context())
    duplicate = service.accept(intake_request(), authorization_context=authorization_context())

    assert first.status is IntakeStatus.ACCEPTED
    assert duplicate.status is IntakeStatus.DUPLICATE
    assert (duplicate.incident_id, duplicate.case_id) == (first.incident_id, first.case_id)
    assert len(state.incidents) == 1
    assert len(state.cases) == 1
    assert len(state.outbox) == 1
    assert len(state.audit) == 2
    assert state.audit[-1].outcome == IntakeStatus.DUPLICATE.value


def test_conflicting_intake_payload_under_same_idempotency_key_fails_closed() -> None:
    state = MemoryState()
    service = make_service(state)
    service.accept(intake_request(), authorization_context=authorization_context())
    conflicting = intake_request().model_copy(update={"report_content": "different report bytes"})

    with pytest.raises(IntakeServiceError, match="immutable raw report could not be stored"):
        service.accept(conflicting, authorization_context=authorization_context())

    assert len(state.incidents) == 1
    assert len(state.cases) == 1
    assert len(state.outbox) == 1
    assert len(state.audit) == 1


def test_mismatched_request_tenant_is_rejected_before_authoritative_write() -> None:
    state = MemoryState()
    with pytest.raises(TenantAuthorizationError, match="authenticated tenant context"):
        make_service(state).accept(
            intake_request(tenant_id=TENANT_B),
            authorization_context=authorization_context(TENANT_A),
        )

    assert state.factory_calls == 0
    assert state.incidents == {}
    assert state.outbox == []


def test_authenticated_identity_without_reviewer_role_is_rejected() -> None:
    state = MemoryState()
    with pytest.raises(TenantAuthorizationError, match="required role"):
        make_service(state).accept(
            intake_request(),
            authorization_context=authorization_context(roles=frozenset({"approver"})),
        )

    assert state.factory_calls == 0


def test_untrusted_report_content_is_not_interpreted_as_event_authority() -> None:
    state = MemoryState()
    make_service(state).accept(intake_request(), authorization_context=authorization_context())
    event = state.outbox[0][1]
    encoded_payload = json.dumps(event.payload, sort_keys=True, separators=(",", ":"))

    assert "ignore policy" not in encoded_payload
    assert "refund" not in encoded_payload
    assert event.aggregate_type == "incident"


def test_external_report_reference_is_preserved_in_immutable_capture() -> None:
    state = MemoryState()
    request = intake_request()
    request = request.model_copy(
        update={
            "report_content": None,
            "report_reference": "merchant://ticket/incident-1",
            "idempotency_key": "external-report-1",
        }
    )

    result = make_service(state).accept(
        request,
        authorization_context=authorization_context(),
    )

    assert result.status is IntakeStatus.ACCEPTED
    assert len(state.raw_report_store.client.objects) == 1
    raw_object = next(iter(state.raw_report_store.client.objects.values()))
    capture = json.loads(raw_object[0])
    assert capture["report_content"] is None
    assert capture["report_reference"] == "merchant://ticket/incident-1"
    reference = json.loads(state.audit[0].evidence_references[0])
    assert reference["reference_id"].startswith("minio://")
    assert reference["checksum"].startswith("sha256:")


@pytest.mark.skipif(
    not os.getenv("RECLAIM_DATABASE_URL"),
    reason="RECLAIM_DATABASE_URL is required for live intake validation",
)
def test_live_postgres_intake_persists_duplicate_safe_case_and_outbox() -> None:
    import psycopg
    from app.db.unit_of_work import PostgresUnitOfWork

    tenant_id = f"live-intake-{uuid4().hex}"
    context = authorization_context(tenant_id)
    database_url = os.environ["RECLAIM_DATABASE_URL"]
    service = IncidentIntakeService(
        unit_of_work_factory=lambda auth_context: PostgresUnitOfWork(
            lambda: psycopg.connect(database_url),
            authorization_context=auth_context,
        ),
        raw_report_store=ImmutableEvidenceStore(InMemoryObjectStorage()),
    )
    request = intake_request(tenant_id=tenant_id, idempotency_key=f"live-{uuid4().hex}")

    with PostgresUnitOfWork(
        lambda: psycopg.connect(database_url), authorization_context=context
    ) as unit_of_work:
        unit_of_work.tenants.create(tenant_id=tenant_id, display_name="Live Intake Validation")

    first = service.accept(request, authorization_context=context)
    duplicate = service.accept(request, authorization_context=context)

    with psycopg.connect(database_url) as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM incidents WHERE tenant_id = %s),
                (SELECT count(*) FROM cases WHERE tenant_id = %s),
                (SELECT count(*) FROM outbox_events WHERE tenant_id = %s),
                (SELECT count(*) FROM audit_records WHERE tenant_id = %s)
            """,
            (tenant_id, tenant_id, tenant_id, tenant_id),
        ).fetchone()

    assert first.status is IntakeStatus.ACCEPTED
    assert duplicate.status is IntakeStatus.DUPLICATE
    assert (first.incident_id, first.case_id) == (duplicate.incident_id, duplicate.case_id)
    assert counts == (1, 1, 1, 2)
