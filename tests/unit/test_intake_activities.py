"""Tests for PostgreSQL-backed case workflow activities."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from temporalio.exceptions import ApplicationError
from workflows.activities.intake import (
    IntakeActivityDependencies,
    make_intake_activities,
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


@dataclass
class Cases:
    row: tuple[object, ...] | None = (
        "tenant-a",
        "case-1",
        "incident-1",
        "intake_received",
        None,
        "reclaim.case.tenant-a.case-1",
        datetime(2026, 8, 30, tzinfo=UTC),
        datetime(2026, 8, 30, tzinfo=UTC),
        None,
    )

    def get(self, *, case_id: str) -> tuple[object, ...] | None:
        return self.row if case_id == "case-1" else None


class UoW:
    def __init__(self, cases: Cases) -> None:
        self.cases = cases

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


def command(tenant_id: str = "tenant-a") -> CaseWorkflowCommand:
    return CaseWorkflowCommand(
        tenant_id=tenant_id,
        case_id="case-1",
        correlation_id="corr-1",
        command_id="command-1",
        stages=("collect_evidence",),
    )


@pytest.mark.asyncio
async def test_activity_returns_authoritative_case_state_and_identity() -> None:
    cases = Cases()
    activities = make_intake_activities(
        IntakeActivityDependencies(
            unit_of_work_factory=lambda _: UoW(cases),
            authorization_context_factory=context,
        )
    )

    result = await activities.read_authoritative_state(command())

    assert result == {
        "tenant_id": "tenant-a",
        "case_id": "case-1",
        "workflow_id": "reclaim.case.tenant-a.case-1",
        "state": "intake_received",
        "authoritative": True,
    }


@pytest.mark.asyncio
async def test_activity_missing_case_is_non_retryable_and_does_not_invent_state() -> (
    None
):
    cases = Cases(row=None)
    activities = make_intake_activities(
        IntakeActivityDependencies(
            unit_of_work_factory=lambda _: UoW(cases),
            authorization_context_factory=context,
        )
    )

    with pytest.raises(ApplicationError, match="not present") as error:
        await activities.recover_authoritative_state(command())

    assert error.value.non_retryable is True


@pytest.mark.asyncio
async def test_activity_rejects_worker_context_that_crosses_command_tenant() -> None:
    activities = make_intake_activities(
        IntakeActivityDependencies(
            unit_of_work_factory=lambda _: UoW(Cases()),
            authorization_context_factory=lambda _: context("tenant-b"),
        )
    )

    with pytest.raises(ApplicationError, match="tenant-bound") as error:
        await activities.read_authoritative_state(command())

    assert error.value.non_retryable is True
