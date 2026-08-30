"""Case intake activities that re-read authoritative PostgreSQL state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.db.unit_of_work import PostgresUnitOfWork
from temporalio import activity
from temporalio.exceptions import ApplicationError

from workflows.case_workflow import case_workflow_id
from workflows.commands import CaseWorkflowCommand

UnitOfWorkFactory = Callable[[TenantAuthorizationContext], PostgresUnitOfWork]
AuthorizationContextFactory = Callable[[str], TenantAuthorizationContext]


@dataclass(frozen=True, slots=True)
class IntakeActivityDependencies:
    """Trusted worker wiring; tenant identity is narrowed by this injected factory."""

    unit_of_work_factory: UnitOfWorkFactory
    authorization_context_factory: AuthorizationContextFactory


class IntakeActivities:
    """Activities for workflow start/recovery, with no workflow-state authority."""

    def __init__(self, dependencies: IntakeActivityDependencies) -> None:
        self.dependencies = dependencies

    @activity.defn(name="case.read_authoritative_state")
    async def read_authoritative_state(self, command: CaseWorkflowCommand) -> dict[str, Any]:
        return self._read_case(command, operation="read")

    @activity.defn(name="case.start_intake")
    async def start_intake(self, command: CaseWorkflowCommand) -> dict[str, Any]:
        return self._read_case(command, operation="start")

    @activity.defn(name="case.recover_authoritative_state")
    async def recover_authoritative_state(self, command: CaseWorkflowCommand) -> dict[str, Any]:
        return self._read_case(command, operation="recover")

    def _read_case(self, command: CaseWorkflowCommand, *, operation: str) -> dict[str, Any]:
        context = self.dependencies.authorization_context_factory(command.tenant_id)
        if (
            context.tenant_id != command.tenant_id
            or context.identity_type is not IdentityType.SERVICE
        ):
            raise ApplicationError(
                "workflow activity service context is not tenant-bound",
                non_retryable=True,
            )
        try:
            with self.dependencies.unit_of_work_factory(context) as unit_of_work:
                row = unit_of_work.cases.get(case_id=command.case_id)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(f"authoritative case {operation} failed") from exc
        if row is None:
            raise ApplicationError(
                "case is not present in authoritative PostgreSQL",
                non_retryable=True,
            )
        if str(row[0]) != command.tenant_id or str(row[1]) != command.case_id:
            raise ApplicationError(
                "authoritative case identity does not match command",
                non_retryable=True,
            )
        return {
            "tenant_id": command.tenant_id,
            "case_id": command.case_id,
            "workflow_id": case_workflow_id(command.tenant_id, command.case_id),
            "state": str(row[3]),
            "authoritative": True,
        }


def make_intake_activities(dependencies: IntakeActivityDependencies) -> IntakeActivities:
    """Build the activity object to register with a Temporal worker."""

    return IntakeActivities(dependencies)
