"""Live Temporal tests for retry, signal, and PostgreSQL authority boundaries.

These tests are intentionally opt-in.  They require a real Temporal endpoint and
PostgreSQL URL; the default test run must not silently replace either dependency
with an in-memory success path.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from workflows.case_workflow import CaseWorkflow, case_workflow_id
from workflows.commands import CaseWorkflowCommand, CaseWorkflowSignal, SignalKind

from backend.tests.integration.support import make_authorization_context

pytestmark = pytest.mark.integration


def _live_settings() -> tuple[str, str]:
    target = os.getenv("RECLAIM_TEMPORAL_TARGET")
    database_url = os.getenv("RECLAIM_DATABASE_URL")
    if not target or not database_url:
        pytest.skip("live Temporal target and PostgreSQL URL are required")
    return target, database_url


@pytest.mark.asyncio
async def test_temporal_retries_activity_and_reads_authoritative_postgres_state() -> (
    None
):
    target, database_url = _live_settings()
    from temporalio import activity
    from temporalio.client import Client
    from temporalio.exceptions import ApplicationError
    from temporalio.worker import Worker

    attempts = 0

    @activity.defn(name="case.read_authoritative_state")
    async def read_authoritative_state(
        command: CaseWorkflowCommand,
    ) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ApplicationError("transient repository connection failure")
        import psycopg
        from app.db.unit_of_work import PostgresUnitOfWork

        with PostgresUnitOfWork(
            lambda: psycopg.connect(database_url),
            authorization_context=make_authorization_context(command.tenant_id),
        ) as unit_of_work:
            row = unit_of_work.cases.get(case_id=command.case_id)
        if row is None:
            raise ApplicationError(
                "case is not present in authoritative PostgreSQL", non_retryable=True
            )
        return {
            "tenant_id": command.tenant_id,
            "case_id": command.case_id,
            "state": row[3],
            "authoritative": True,
        }

    @activity.defn(name="case.collect_evidence")
    async def collect_evidence(command: CaseWorkflowCommand) -> dict[str, object]:
        return {
            "tenant_id": command.tenant_id,
            "case_id": command.case_id,
            "state": "collecting_evidence",
            "authoritative": True,
        }

    tenant_id = "tenant-a"
    case_id = f"temporal-{uuid.uuid4().hex}"
    incident_id = f"incident-{uuid.uuid4().hex}"
    import psycopg

    with psycopg.connect(database_url) as connection:
        connection.execute(
            "INSERT INTO incidents (tenant_id, incident_id, source, received_at, correlation_key, intake_status, deduplication_identity) VALUES (%s, %s, 'temporal-test', %s, %s, 'accepted', %s)",
            (
                tenant_id,
                incident_id,
                datetime.now(UTC),
                f"corr-{case_id}",
                f"dedupe-{case_id}",
            ),
        )
        connection.execute(
            "INSERT INTO cases (tenant_id, case_id, incident_id, current_state, workflow_id) VALUES (%s, %s, %s, 'intake_received', %s)",
            (tenant_id, case_id, incident_id, case_workflow_id(tenant_id, case_id)),
        )
        connection.commit()

    client = await Client.connect(target)
    task_queue = f"reclaim-temporal-{uuid.uuid4().hex}"
    command = CaseWorkflowCommand(
        tenant_id=tenant_id,
        case_id=case_id,
        correlation_id=f"corr-{case_id}",
        command_id=f"command-{case_id}",
        stages=("collect_evidence",),
    )
    workflow_id = case_workflow_id(tenant_id, case_id)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[CaseWorkflow],
        activities=[read_authoritative_state, collect_evidence],
    )
    async with worker:
        handle = await client.start_workflow(
            CaseWorkflow.run,
            command,
            id=workflow_id,
            task_queue=task_queue,
        )
        result = await handle.result()

    assert attempts == 2
    assert result.case_id == case_id
    assert result.terminal_state is None


@pytest.mark.asyncio
async def test_temporal_signal_wakes_waiting_workflow_without_business_state_in_history() -> (
    None
):
    target, _ = _live_settings()
    from temporalio import activity
    from temporalio.client import Client
    from temporalio.worker import Worker

    authoritative_state = "intake_received"

    @activity.defn(name="case.read_authoritative_state")
    async def read_authoritative_state(
        command: CaseWorkflowCommand,
    ) -> dict[str, object]:
        return {
            "tenant_id": command.tenant_id,
            "case_id": command.case_id,
            "state": authoritative_state,
            "authoritative": True,
        }

    @activity.defn(name="case.rebuild_timeline")
    async def rebuild_timeline(command: CaseWorkflowCommand) -> dict[str, object]:
        nonlocal authoritative_state
        authoritative_state = "timeline_ready"
        return {
            "tenant_id": command.tenant_id,
            "case_id": command.case_id,
            "state": "timeline_ready",
            "wait_for": "approval",
            "authoritative": True,
        }

    tenant_id = "tenant-a"
    case_id = f"temporal-signal-{uuid.uuid4().hex}"
    command = CaseWorkflowCommand(
        tenant_id=tenant_id,
        case_id=case_id,
        correlation_id=f"corr-{case_id}",
        command_id=f"command-{case_id}",
        stages=("rebuild_timeline",),
    )
    client = await Client.connect(target)
    task_queue = f"reclaim-temporal-signal-{uuid.uuid4().hex}"
    workflow_id = case_workflow_id(tenant_id, case_id)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[CaseWorkflow],
        activities=[read_authoritative_state, rebuild_timeline],
    )
    await worker.__aenter__()
    try:
        handle = await client.start_workflow(
            CaseWorkflow.run,
            command,
            id=workflow_id,
            task_queue=task_queue,
        )
        for _ in range(50):
            status = await handle.query(CaseWorkflow.status)
            if status.state == "action_pending":
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("workflow did not reach approval wait")
    finally:
        await worker.__aexit__(None, None, None)

    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[CaseWorkflow],
        activities=[read_authoritative_state, rebuild_timeline],
    ):
        await handle.signal(
            CaseWorkflow.signal,
            CaseWorkflowSignal(
                tenant_id=tenant_id,
                case_id=case_id,
                correlation_id=command.correlation_id,
                kind=SignalKind.APPROVAL_RECORDED,
                reference="approval-test-only",
            ),
        )
        result = await handle.result()

    assert result.completed_stages == ("rebuild_timeline",)
