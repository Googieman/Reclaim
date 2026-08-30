"""Unit tests for authenticated Temporal command dispatch."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Self

import jwt
import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from api.workflow_commands import (
    CaseWorkflowCommandService,
    WorkflowCommandError,
)
from workflows.case_workflow import case_workflow_id
from workflows.commands import CaseWorkflowCommand, CaseWorkflowSignal, SignalKind


def context(tenant_id: str = "tenant-a", roles: frozenset[str] | None = None):
    principal = AuthenticatedPrincipal(
        subject="reviewer-1",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: roles or frozenset({"reviewer", "approver"})},
        identity_type=IdentityType.USER,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


@dataclass
class Cases:
    row: tuple[object, ...] | None = (
        "tenant-a",
        "case-1",
        "incident-1",
        "intake_received",
        None,
        None,
        datetime(2026, 8, 30, tzinfo=UTC),
        datetime(2026, 8, 30, tzinfo=UTC),
        None,
    )
    bound_workflow_id: str | None = None

    def get(self, *, case_id: str) -> tuple[object, ...] | None:
        return self.row if case_id == "case-1" else None

    def bind_workflow(self, *, case_id: str, workflow_id: str) -> tuple[object, ...]:
        self.bound_workflow_id = workflow_id
        return self.row  # type: ignore[return-value]


class UoW:
    def __init__(self, cases: Cases) -> None:
        self.cases = cases

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


class Handle:
    def __init__(self) -> None:
        self.signals: list[Any] = []

    async def signal(self, workflow: Any, signal: Any) -> None:
        self.signals.append((workflow, signal))


class Temporal:
    def __init__(self) -> None:
        self.starts: list[Any] = []
        self.handle = Handle()

    async def start_workflow(
        self, workflow: Any, arg: Any, *, id: str, task_queue: str
    ) -> None:
        self.starts.append((workflow, arg, id, task_queue))

    def get_workflow_handle(self, workflow_id: str) -> Handle:
        assert workflow_id == case_workflow_id("tenant-a", "case-1")
        return self.handle


def make_service() -> tuple[CaseWorkflowCommandService, Cases, Temporal]:
    cases = Cases()
    temporal = Temporal()
    service = CaseWorkflowCommandService(
        temporal_client=temporal,
        unit_of_work_factory=lambda _: UoW(cases),
    )
    return service, cases, temporal


@pytest.mark.asyncio
async def test_start_binds_deterministic_workflow_metadata_after_authoritative_case_check() -> (
    None
):
    service, cases, temporal = make_service()
    command = CaseWorkflowCommand(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        command_id="command-1",
        stages=("collect_evidence",),
    )

    result = await service.start_case(command, authorization_context=context())

    assert result.started is True
    assert result.workflow_id == "reclaim.case.tenant-a.case-1"
    assert cases.bound_workflow_id == result.workflow_id
    assert temporal.starts[0][2] == result.workflow_id


@pytest.mark.asyncio
async def test_signal_checks_authoritative_case_and_preserves_tenant_identity() -> None:
    service, _, temporal = make_service()
    signal = CaseWorkflowSignal(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        kind=SignalKind.DEPENDENCY_AVAILABLE,
        reference="evidence-ready",
    )

    result = await service.signal_case(signal, authorization_context=context())

    assert result.signal_kind is SignalKind.DEPENDENCY_AVAILABLE
    assert temporal.handle.signals[0][1] == signal


@pytest.mark.asyncio
async def test_workflow_command_cannot_use_request_tenant_as_authority() -> None:
    service, _, _ = make_service()
    command = CaseWorkflowCommand(
        tenant_id="tenant-b",
        case_id="case-1",
        correlation_id="corr-1",
        command_id="command-1",
        stages=("collect_evidence",),
    )

    with pytest.raises(PermissionError, match="authenticated context"):
        await service.start_case(command, authorization_context=context())


@pytest.mark.asyncio
async def test_terminal_case_cannot_be_started() -> None:
    service, cases, _ = make_service()
    cases.row = (*cases.row[:3], "verified_failed", *cases.row[4:])  # type: ignore[index]
    command = CaseWorkflowCommand(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        command_id="command-1",
        stages=("collect_evidence",),
    )

    with pytest.raises(WorkflowCommandError, match="terminal"):
        await service.start_case(command, authorization_context=context())


def test_workflow_router_uses_verified_path_tenant_and_allowlisted_stages() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.workflow_commands import create_workflow_router

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "test-issuer",
            "aud": "workflow-api",
            "sub": "reviewer-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "tenant_ids": ["tenant-a"],
            "tenant_roles": {"tenant-a": ["reviewer", "approver"]},
        },
        "test-key",
        algorithm="HS256",
    )
    service, _, _ = make_service()
    verifier = __import__("app.auth.oidc", fromlist=["OIDCVerifier"]).OIDCVerifier(
        issuer="test-issuer",
        audience="workflow-api",
        signing_key="test-key",
        algorithms=("HS256",),
    )
    app = FastAPI()
    app.include_router(
        create_workflow_router(command_service=service, oidc_verifier=verifier)
    )

    with TestClient(app) as client:
        response = client.post(
            "/tenants/tenant-a/cases/case-1/workflow",
            json={
                "correlation_id": "corr-router-1",
                "command_id": "command-router-1",
                "stages": ["start_intake"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        forbidden_stage = client.post(
            "/tenants/tenant-a/cases/case-1/workflow",
            json={
                "correlation_id": "corr-router-2",
                "command_id": "command-router-2",
                "stages": ["arbitrary_network"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["workflow_id"] == "reclaim.case.tenant-a.case-1"
    assert forbidden_stage.status_code == 422
