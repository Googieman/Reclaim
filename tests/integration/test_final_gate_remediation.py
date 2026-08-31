"""Opt-in live PostgreSQL coverage for the final US1 remediation gate."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from threading import Barrier
from uuid import uuid4

import pytest

from app.audit.chain import AuditChain, checksum_for_record
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.timeline_events import build_timeline_rebuilt_event
from evidence.models import NormalizedFact
from timeline.reconstruct import TimelineReconstructor

from packages.contracts.audit_replay import AuditRecord

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("RECLAIM_DATABASE_URL")
    if not value:
        pytest.skip(
            "RECLAIM_DATABASE_URL is required for final-gate PostgreSQL validation"
        )
    return value


def _context(tenant_id: str):
    principal = AuthenticatedPrincipal(
        subject="final-gate-worker",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="final-gate-test",
    )
    return principal.for_tenant(tenant_id)


def _factory(database_url: str):
    return lambda authorization_context: PostgresUnitOfWork(
        lambda: _connect(database_url),
        authorization_context=authorization_context,
    )


def _connect(database_url: str):
    import psycopg

    return psycopg.connect(database_url)


def _seed_tenant(database_url: str, tenant_id: str) -> None:
    context = _context(tenant_id)
    with _factory(database_url)(context) as unit_of_work:
        unit_of_work.tenants.create(tenant_id=tenant_id, display_name="Final Gate Test")


def test_live_concurrent_audit_appends_have_one_verified_linear_chain() -> None:
    database_url = _database_url()
    tenant_id = f"audit-final-{uuid4().hex}"
    _seed_tenant(database_url, tenant_id)
    writer_count = 12
    start = Barrier(writer_count)

    def append_one(index: int):
        start.wait()
        context = _context(tenant_id)
        with _factory(database_url)(context) as unit_of_work:
            chain = AuditChain(unit_of_work.audit)
            record = chain.build_record(
                tenant_id=tenant_id,
                audit_id=f"audit-{index}-{uuid4().hex}",
                case_id=None,
                actor="final-gate-test",
                action="audit.concurrent-test",
                correlation_ids=(f"corr-{index}",),
                outcome="accepted",
                recorded_at=datetime(2026, 8, 31, tzinfo=UTC)
                + timedelta(seconds=index),
            )
            return chain.append(record)

    with ThreadPoolExecutor(max_workers=writer_count) as executor:
        appended = list(executor.map(append_one, range(writer_count)))

    with _connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT tenant_id, audit_id, case_id, actor, action, input_references,
                   output_references, evidence_references, policy_version_id,
                   model_version, provider_version, approval_id, execution_id,
                   correlation_ids, outcome, recorded_at, previous_record_checksum,
                   record_checksum, chain_sequence
            FROM audit_records
            WHERE tenant_id = %s
            ORDER BY chain_sequence
            """,
            (tenant_id,),
        ).fetchall()

    assert len(appended) == writer_count
    assert len(rows) == writer_count
    assert sum(row[16] is None for row in rows) == 1
    previous_checksum = None
    for row in rows:
        record = AuditRecord(
            tenant_id=str(row[0]),
            correlation_id=str(row[13][0]) if row[13] else str(row[1]),
            audit_id=str(row[1]),
            case_id=None if row[2] is None else str(row[2]),
            actor=str(row[3]),
            action=str(row[4]),
            input_references=tuple(row[5]),
            output_references=tuple(row[6]),
            evidence_references=tuple(row[7]),
            policy_version_id=None if row[8] is None else str(row[8]),
            model_version=None if row[9] is None else str(row[9]),
            provider_version=None if row[10] is None else str(row[10]),
            approval_id=None if row[11] is None else str(row[11]),
            execution_id=None if row[12] is None else str(row[12]),
            correlation_ids=tuple(row[13]),
            outcome=str(row[14]),
            recorded_at=row[15],
            previous_record_checksum=None if row[16] is None else str(row[16]),
            record_checksum=str(row[17]),
        )
        assert record.previous_record_checksum == previous_checksum
        assert checksum_for_record(record) == record.record_checksum
        previous_checksum = record.record_checksum
        assert row[18] is not None

    with _factory(database_url)(_context(tenant_id)) as unit_of_work:
        assert AuditChain(unit_of_work.audit).append(appended[0]) == appended[0]
    with _connect(database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_records WHERE tenant_id = %s", (tenant_id,)
        ).fetchone() == (writer_count,)


def test_live_audit_chain_partitions_are_independent_across_tenants() -> None:
    database_url = _database_url()
    tenants = (f"audit-tenant-a-{uuid4().hex}", f"audit-tenant-b-{uuid4().hex}")
    for tenant_id in tenants:
        _seed_tenant(database_url, tenant_id)

    def append_root(tenant_id: str) -> None:
        with _factory(database_url)(_context(tenant_id)) as unit_of_work:
            record = AuditChain(unit_of_work.audit).build_record(
                tenant_id=tenant_id,
                audit_id=f"audit-{uuid4().hex}",
                case_id=None,
                actor="final-gate-test",
                action="audit.tenant-isolation-test",
                outcome="accepted",
                recorded_at=datetime(2026, 8, 31, tzinfo=UTC),
            )
            AuditChain(unit_of_work.audit).append(record)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(append_root, tenants))
    with _connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT tenant_id, count(*), count(*) FILTER (
                WHERE previous_record_checksum IS NULL
            )
            FROM audit_records
            WHERE tenant_id = ANY(%s)
            GROUP BY tenant_id
            ORDER BY tenant_id
            """,
            (list(tenants),),
        ).fetchall()
    assert rows == [(tenants[0], 1, 1), (tenants[1], 1, 1)]


def test_live_audit_rollback_releases_chain_without_leaving_a_root() -> None:
    database_url = _database_url()
    tenant_id = f"audit-rollback-{uuid4().hex}"
    _seed_tenant(database_url, tenant_id)
    context = _context(tenant_id)

    with pytest.raises(RuntimeError, match="final-gate-rollback"):
        with _factory(database_url)(context) as unit_of_work:
            chain = AuditChain(unit_of_work.audit)
            record = chain.build_record(
                tenant_id=tenant_id,
                audit_id="audit-rollback",
                case_id=None,
                actor="final-gate-test",
                action="audit.rollback-test",
                outcome="accepted",
                recorded_at=datetime(2026, 8, 31, tzinfo=UTC),
            )
            chain.append(record)
            raise RuntimeError("final-gate-rollback")

    with _connect(database_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_records WHERE tenant_id = %s", (tenant_id,)
        ).fetchone() == (0,)


def _fact(
    *, tenant_id: str, case_id: str, source_event_id: str, payload: dict[str, object]
) -> NormalizedFact:
    timestamp = datetime(2026, 8, 31, 8, tzinfo=UTC)
    return NormalizedFact(
        tenant_id=tenant_id,
        case_id=case_id,
        evidence_id=f"evidence-{source_event_id}",
        resource_type="payments",
        source_identity=(
            "merchant-ledger"
            if source_event_id.startswith("fallback")
            else "razorpay-test"
        ),
        source_event_id=source_event_id,
        canonical_event_type="payment.captured",
        dedupe_key="payment:p-1",
        effective_at=timestamp,
        observed_at=timestamp,
        received_at=timestamp + timedelta(minutes=1),
        event_at=timestamp,
        source_priority=20 if source_event_id.startswith("fallback") else 10,
        payload=payload,
        evidence_references=(f"evidence-{source_event_id}",),
    )


def test_live_timeline_conflict_survives_postgres_readback_and_outbox() -> None:
    database_url = _database_url()
    tenant_id = f"timeline-final-{uuid4().hex}"
    case_id = f"case-{uuid4().hex}"
    incident_id = f"incident-{uuid4().hex}"
    context = _context(tenant_id)
    factory = _factory(database_url)
    timestamp = datetime(2026, 8, 31, 8, tzinfo=UTC)

    with factory(context) as unit_of_work:
        unit_of_work.tenants.create(
            tenant_id=tenant_id, display_name="Timeline Final Gate"
        )
        unit_of_work.incidents.create(
            incident_id=incident_id,
            source="final-gate-test",
            reporter_context={},
            received_at=timestamp,
            correlation_key=f"corr-{incident_id}",
            raw_input_reference=None,
            intake_status="accepted",
            deduplication_identity=f"dedupe-{incident_id}",
        )
        unit_of_work.cases.create(
            case_id=case_id,
            incident_id=incident_id,
            current_state="intake_received",
            created_at=timestamp,
        )

    provider = _fact(
        tenant_id=tenant_id,
        case_id=case_id,
        source_event_id="provider-1",
        payload={"status": "captured"},
    )
    fallback = _fact(
        tenant_id=tenant_id,
        case_id=case_id,
        source_event_id="fallback-1",
        payload={"status": "authorized"},
    )
    result = TimelineReconstructor(unit_of_work_factory=factory).rebuild(
        case_id=case_id,
        evidence=(),
        normalized_facts=(fallback, provider),
        authorization_context=context,
    )

    with factory(context) as unit_of_work:
        persisted_uncertainty = unit_of_work.cases.timeline_uncertainty(case_id=case_id)
        persisted_events = unit_of_work.timeline.for_case(case_id=case_id)
        authoritative_event = unit_of_work.outbox.reconcile_authority(
            build_timeline_rebuilt_event(result)
        )
    with _connect(database_url) as connection:
        outbox_payload = connection.execute(
            """
            SELECT payload
            FROM outbox_events
            WHERE tenant_id = %s AND event_type = 'timeline.rebuilt'
              AND aggregate_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (tenant_id, case_id),
        ).fetchone()[0]

    assert result.uncertainty == ("payment:p-1:conflicting_sources",)
    assert persisted_uncertainty == result.uncertainty
    assert persisted_events[0][10] == ["fallback-1"]
    assert persisted_events[0][11] == ["conflicting_sources"]
    assert tuple(outbox_payload["uncertainty"]) == result.uncertainty
    assert outbox_payload["events"][0]["conflicting_source_event_ids"] == ["fallback-1"]
    assert authoritative_event.payload == outbox_payload
    assert (
        authoritative_event.payload_checksum
        == build_timeline_rebuilt_event(result).payload_checksum
    )
    replay = TimelineReconstructor().rebuild(
        case_id=case_id,
        evidence=(),
        normalized_facts=(provider, fallback),
        authorization_context=context,
    )
    assert replay.uncertainty == result.uncertainty
