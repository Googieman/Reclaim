"""Live failure-recovery coverage for the production US1 Temporal workflow."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from app.db.unit_of_work import PostgresUnitOfWork
from app.storage.minio_evidence import ImmutableEvidenceStore
from connectors.simulators.evidence import build_default_evidence_simulators
from evidence.orchestrator import EvidenceOrchestrator
from evidence.storage import EvidenceStorage, InMemoryObjectStorage
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner
from timeline.reconstruct import TimelineReconstructor
from workflows.case_workflow import CaseWorkflow, case_workflow_id
from workflows.commands import CaseWorkflowCommand
from workflows.worker import CaseWorkerDependencies, create_case_worker

from backend.tests.integration.support import make_authorization_context

pytestmark = pytest.mark.integration


def _live_settings() -> tuple[str, str]:
    target = os.getenv("RECLAIM_TEMPORAL_TARGET")
    database_url = os.getenv("RECLAIM_DATABASE_URL")
    if not target or not database_url:
        pytest.skip("live Temporal target and PostgreSQL URL are required")
    return target, database_url


def _factory(database_url: str):
    return lambda context: PostgresUnitOfWork(
        lambda: __import__("psycopg").connect(database_url),
        authorization_context=context,
    )


def _seed_case(database_url: str, tenant_id: str, case_id: str) -> None:
    incident_id = f"incident-{uuid.uuid4().hex}"
    with __import__("psycopg").connect(database_url) as connection:
        connection.execute(
            "INSERT INTO tenants (tenant_id, display_name) VALUES (%s, %s)",
            (tenant_id, "US1 Temporal Recovery"),
        )
        connection.execute(
            """
            INSERT INTO incidents (
                tenant_id, incident_id, source, received_at, correlation_key,
                intake_status, deduplication_identity
            ) VALUES (%s, %s, 'temporal-test', %s, %s, 'accepted', %s)
            """,
            (tenant_id, incident_id, datetime.now(UTC), f"corr-{case_id}", case_id),
        )
        connection.execute(
            """
            INSERT INTO cases (tenant_id, case_id, incident_id, current_state)
            VALUES (%s, %s, %s, 'intake_received')
            """,
            (tenant_id, case_id, incident_id),
        )
        connection.commit()


def _dependencies(
    database_url: str,
    tenant_id: str,
    *,
    timeline_reconstructor: TimelineReconstructor | None = None,
    unit_of_work_factory: Any | None = None,
) -> CaseWorkerDependencies:
    factory = unit_of_work_factory or _factory(database_url)
    storage = EvidenceStorage(ImmutableEvidenceStore(InMemoryObjectStorage()))
    return CaseWorkerDependencies(
        unit_of_work_factory=factory,
        authorization_context_factory=lambda value: make_authorization_context(value),
        evidence_orchestrator=EvidenceOrchestrator(
            build_default_evidence_simulators(tenant_id),
            storage=storage,
            unit_of_work_factory=factory,
        ),
        evidence_storage=storage,
        timeline_reconstructor=timeline_reconstructor
        or TimelineReconstructor(unit_of_work_factory=factory),
    )


@pytest.mark.asyncio
async def test_production_us1_workflow_retries_and_verifies_postgres_state() -> None:
    target, database_url = _live_settings()
    tenant_id = f"temporal-us1-{uuid.uuid4().hex}"
    case_id = f"case-{uuid.uuid4().hex}"
    _seed_case(database_url, tenant_id, case_id)
    attempts = 0
    real_factory = _factory(database_url)

    def retrying_factory(context: Any) -> Any:
        nonlocal attempts
        if attempts == 0:
            attempts += 1
            raise ConnectionError("test-only transient PostgreSQL connection failure")
        return real_factory(context)

    client = await Client.connect(target)
    queue = f"temporal-us1-retry-{uuid.uuid4().hex}"
    dependencies = _dependencies(
        database_url,
        tenant_id,
        unit_of_work_factory=retrying_factory,
    )
    command = CaseWorkflowCommand(
        tenant_id=tenant_id,
        case_id=case_id,
        correlation_id=f"corr-{case_id}",
        command_id=f"command-{case_id}",
    )
    async with create_case_worker(
        client,
        dependencies,
        task_queue=queue,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        handle = await client.start_workflow(
            CaseWorkflow.run,
            command,
            id=case_workflow_id(tenant_id, case_id),
            task_queue=queue,
        )
        result = await handle.result()

    assert attempts == 1
    assert result.completed_stages == ("collect_evidence", "rebuild_timeline")
    assert result.authoritative_state == "timeline_ready"
    with __import__("psycopg").connect(database_url) as connection:
        state = connection.execute(
            "SELECT current_state FROM cases WHERE tenant_id = %s AND case_id = %s",
            (tenant_id, case_id),
        ).fetchone()
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM evidence_items WHERE tenant_id = %s AND case_id = %s),
                (SELECT count(*) FROM timeline_events WHERE tenant_id = %s AND case_id = %s)
            """,
            (tenant_id, case_id, tenant_id, case_id),
        ).fetchone()
    assert state == ("timeline_ready",)
    assert counts == (6, 6)


@pytest.mark.asyncio
async def test_production_us1_workflow_recovers_after_worker_restart() -> None:
    target, database_url = _live_settings()
    tenant_id = f"temporal-us1-restart-{uuid.uuid4().hex}"
    case_id = f"case-{uuid.uuid4().hex}"
    _seed_case(database_url, tenant_id, case_id)
    failure_seen = asyncio.Event()
    delegate = TimelineReconstructor(unit_of_work_factory=_factory(database_url))

    class FailOnceReconstructor:
        def __init__(self) -> None:
            self.failed = False

        def rebuild(self, **kwargs: Any) -> Any:
            if not self.failed:
                self.failed = True
                failure_seen.set()
                raise ConnectionError("test-only timeline activity failure")
            return delegate.rebuild(**kwargs)

    client = await Client.connect(target)
    queue = f"temporal-us1-restart-{uuid.uuid4().hex}"
    dependencies = _dependencies(
        database_url,
        tenant_id,
        timeline_reconstructor=FailOnceReconstructor(),  # type: ignore[arg-type]
    )
    command = CaseWorkflowCommand(
        tenant_id=tenant_id,
        case_id=case_id,
        correlation_id=f"corr-{case_id}",
        command_id=f"command-{case_id}",
    )
    handle = None
    async with create_case_worker(
        client,
        dependencies,
        task_queue=queue,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        handle = await client.start_workflow(
            CaseWorkflow.run,
            command,
            id=case_workflow_id(tenant_id, case_id),
            task_queue=queue,
        )
        await asyncio.wait_for(failure_seen.wait(), timeout=30)

    assert handle is not None
    async with create_case_worker(
        client,
        dependencies,
        task_queue=queue,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        result = await handle.result()

    assert result.completed_stages == ("collect_evidence", "rebuild_timeline")
    assert result.authoritative_state == "timeline_ready"
    with __import__("psycopg").connect(database_url) as connection:
        state = connection.execute(
            "SELECT current_state FROM cases WHERE tenant_id = %s AND case_id = %s",
            (tenant_id, case_id),
        ).fetchone()
    assert state == ("timeline_ready",)
