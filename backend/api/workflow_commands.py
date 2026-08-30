"""Authenticated API boundary for starting and signaling case workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.auth.oidc import RequiredRole, TenantAuthorizationContext, TenantAuthorizationError
from app.db.unit_of_work import PostgresUnitOfWork
from pydantic import BaseModel, ConfigDict, Field, model_validator
from workflows.case_workflow import CASE_WORKFLOW_NAME, CaseWorkflow, case_workflow_id
from workflows.commands import (
    CaseWorkflowCommand,
    CaseWorkflowSignal,
    RecoveryCommand,
    SignalKind,
)


class WorkflowClient(Protocol):
    async def start_workflow(self, workflow: Any, arg: Any, *, id: str, task_queue: str) -> Any: ...

    def get_workflow_handle(self, workflow_id: str) -> Any: ...


UnitOfWorkFactory = Callable[[TenantAuthorizationContext], PostgresUnitOfWork]
API_ALLOWED_STAGES = frozenset(
    {
        "start_intake",
        "collect_evidence",
        "rebuild_timeline",
        "analyze_case",
        "evaluate_policy",
        "execute_actions",
        "verify_case",
    }
)


@dataclass(frozen=True, slots=True)
class WorkflowStartResult:
    tenant_id: str
    case_id: str
    workflow_id: str
    started: bool


@dataclass(frozen=True, slots=True)
class WorkflowSignalResult:
    tenant_id: str
    case_id: str
    workflow_id: str
    signal_kind: SignalKind


class WorkflowStartRequest(BaseModel):
    """HTTP body; tenant identity is deliberately absent and comes from the path/auth."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    expected_state: str = Field(default="intake_received", min_length=1)
    stages: tuple[str, ...] = ("start_intake",)

    @model_validator(mode="after")
    def validate_stages(self) -> WorkflowStartRequest:
        if not self.stages or any(stage not in API_ALLOWED_STAGES for stage in self.stages):
            raise ValueError("workflow stages are not allowlisted")
        return self


class WorkflowSignalRequest(BaseModel):
    """HTTP signal body without a caller-controlled tenant field."""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str = Field(min_length=1)
    kind: SignalKind
    reference: str | None = None


class WorkflowCommandError(RuntimeError):
    """Raised when a workflow command cannot be safely dispatched."""


class CaseWorkflowCommandService:
    """Check PostgreSQL case authority before dispatching durable Temporal intent."""

    def __init__(
        self,
        *,
        temporal_client: WorkflowClient,
        unit_of_work_factory: UnitOfWorkFactory,
        task_queue: str = "reclaim-case-workflows",
    ) -> None:
        if not task_queue.strip():
            raise ValueError("workflow task queue is required")
        self.temporal_client = temporal_client
        self.unit_of_work_factory = unit_of_work_factory
        self.task_queue = task_queue

    async def start_case(
        self,
        command: CaseWorkflowCommand,
        *,
        authorization_context: TenantAuthorizationContext,
    ) -> WorkflowStartResult:
        _require_context(command.tenant_id, authorization_context)
        authorization_context.require_role(RequiredRole.REVIEWER)
        workflow_id = case_workflow_id(command.tenant_id, command.case_id)
        self._bind_existing_case(workflow_id, command, authorization_context)
        try:
            await self.temporal_client.start_workflow(
                CaseWorkflow.run,
                command,
                id=workflow_id,
                task_queue=self.task_queue,
            )
        except _workflow_already_started_errors():
            return WorkflowStartResult(command.tenant_id, command.case_id, workflow_id, False)
        return WorkflowStartResult(command.tenant_id, command.case_id, workflow_id, True)

    async def signal_case(
        self,
        signal: CaseWorkflowSignal,
        *,
        authorization_context: TenantAuthorizationContext,
    ) -> WorkflowSignalResult:
        _require_context(signal.tenant_id, authorization_context)
        if signal.kind is SignalKind.APPROVAL_RECORDED:
            authorization_context.require_role(RequiredRole.APPROVER)
        else:
            authorization_context.require_role(RequiredRole.REVIEWER)
        self._require_case(signal.case_id, signal.tenant_id, authorization_context)
        workflow_id = case_workflow_id(signal.tenant_id, signal.case_id)
        handle = self.temporal_client.get_workflow_handle(workflow_id)
        await handle.signal(CaseWorkflow.signal, signal)
        return WorkflowSignalResult(
            signal.tenant_id,
            signal.case_id,
            workflow_id,
            signal.kind,
        )

    async def recover_case(
        self,
        command: RecoveryCommand,
        *,
        authorization_context: TenantAuthorizationContext,
    ) -> WorkflowSignalResult:
        _require_context(command.tenant_id, authorization_context)
        authorization_context.require_role(RequiredRole.REVIEWER)
        self._require_case(command.case_id, command.tenant_id, authorization_context)
        workflow_id = case_workflow_id(command.tenant_id, command.case_id)
        await self.temporal_client.get_workflow_handle(workflow_id).signal(
            CaseWorkflow.recover, command
        )
        return WorkflowSignalResult(
            command.tenant_id,
            command.case_id,
            workflow_id,
            SignalKind.RECOVERY_REQUESTED,
        )

    def _bind_existing_case(
        self,
        workflow_id: str,
        command: CaseWorkflowCommand,
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            row = unit_of_work.cases.get(case_id=command.case_id)
            if row is None:
                raise WorkflowCommandError("case is not present in authoritative PostgreSQL")
            if str(row[0]) != command.tenant_id or str(row[1]) != command.case_id:
                raise WorkflowCommandError("case identity does not match authenticated tenant")
            if str(row[3]) in {"verified_contained", "verified_failed", "escalated_unresolved"}:
                raise WorkflowCommandError("terminal case cannot start a workflow")
            if str(row[3]) != command.expected_state:
                raise WorkflowCommandError("case state does not match workflow command")
            if row[5] is not None and str(row[5]) != workflow_id:
                raise WorkflowCommandError("case is already bound to another workflow")
            unit_of_work.cases.bind_workflow(case_id=command.case_id, workflow_id=workflow_id)

    def _require_case(
        self,
        case_id: str,
        tenant_id: str,
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            row = unit_of_work.cases.get(case_id=case_id)
        if row is None or str(row[0]) != tenant_id or str(row[1]) != case_id:
            raise WorkflowCommandError("case is not present in authoritative PostgreSQL")


def _require_context(tenant_id: str, context: TenantAuthorizationContext) -> None:
    if context.tenant_id != tenant_id:
        raise TenantAuthorizationError(
            "workflow command tenant does not match authenticated context"
        )


def _workflow_already_started_errors() -> tuple[type[BaseException], ...]:
    from temporalio.exceptions import WorkflowAlreadyStartedError

    return (WorkflowAlreadyStartedError,)


def create_workflow_router(
    *, command_service: CaseWorkflowCommandService, oidc_verifier: Any
) -> Any:
    """Create authenticated FastAPI routes without trusting body tenant fields."""

    try:
        from fastapi import APIRouter, Header, HTTPException, status
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise RuntimeError("FastAPI is required to construct workflow routes") from exc

    router = APIRouter()

    @router.post("/tenants/{tenant_id}/cases/{case_id}/workflow")
    async def start(
        tenant_id: str,
        case_id: str,
        body: WorkflowStartRequest,
        authorization: str | None = Header(default=None),
    ) -> Any:
        context = _authorize(oidc_verifier, authorization, tenant_id, RequiredRole.REVIEWER)
        command = CaseWorkflowCommand(
            tenant_id=context.tenant_id,
            case_id=case_id,
            correlation_id=body.correlation_id,
            command_id=body.command_id,
            expected_state=body.expected_state,
            stages=body.stages,
        )
        try:
            return await command_service.start_case(command, authorization_context=context)
        except (WorkflowCommandError, TenantAuthorizationError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @router.post("/tenants/{tenant_id}/cases/{case_id}/workflow/signals")
    async def signal(
        tenant_id: str,
        case_id: str,
        body: WorkflowSignalRequest,
        authorization: str | None = Header(default=None),
    ) -> Any:
        required_role = (
            RequiredRole.APPROVER
            if body.kind is SignalKind.APPROVAL_RECORDED
            else RequiredRole.REVIEWER
        )
        context = _authorize(oidc_verifier, authorization, tenant_id, required_role)
        signal_value = CaseWorkflowSignal(
            tenant_id=context.tenant_id,
            case_id=case_id,
            correlation_id=body.correlation_id,
            kind=body.kind,
            reference=body.reference,
        )
        try:
            return await command_service.signal_case(signal_value, authorization_context=context)
        except (WorkflowCommandError, TenantAuthorizationError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return router


def _authorize(
    oidc_verifier: Any,
    authorization: str | None,
    tenant_id: str,
    role: RequiredRole,
) -> Any:
    if authorization is None:
        raise _unauthorized()
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise _unauthorized()
    try:
        return oidc_verifier.authorize(token.strip(), tenant_id=tenant_id, required_role=role)
    except TenantAuthorizationError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="workflow command is not authorized",
        ) from exc


def _unauthorized() -> Any:
    from fastapi import HTTPException

    return HTTPException(status_code=401, detail="bearer authentication is required")


__all__ = [
    "CASE_WORKFLOW_NAME",
    "CaseWorkflowCommandService",
    "WorkflowCommandError",
    "WorkflowSignalResult",
    "WorkflowSignalRequest",
    "WorkflowStartRequest",
    "WorkflowStartResult",
    "create_workflow_router",
]
