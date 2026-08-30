"""Temporal orchestration for a tenant-scoped case.

The workflow deliberately invokes named activities instead of importing database
repositories.  Temporal history is durable orchestration state; each activity must
re-read and validate authoritative PostgreSQL state before returning a transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from .commands import (
    CaseWorkflowCommand,
    CaseWorkflowSignal,
    RecoveryCommand,
    RecoveryKind,
    SignalKind,
)

CASE_WORKFLOW_NAME = "reclaim.case.v1"
ACTIVITY_NAMES = {
    "read_authoritative_state": "case.read_authoritative_state",
    "recover_authoritative_state": "case.recover_authoritative_state",
    "start_intake": "case.start_intake",
    "collect_evidence": "case.collect_evidence",
    "rebuild_timeline": "case.rebuild_timeline",
    "analyze_case": "case.analyze_case",
    "evaluate_policy": "case.evaluate_policy",
    "execute_actions": "case.execute_actions",
    "verify_case": "case.verify_case",
    "reconcile_action": "case.reconcile_action",
    "escalate_unresolved": "case.escalate_unresolved",
}

ACTIVITY_TIMEOUTS = {
    "default": timedelta(minutes=2),
    "reconcile": timedelta(minutes=5),
    "escalate": timedelta(minutes=2),
}

RETRY_POLICIES = {
    "repository": RetryPolicy(
        initial_interval=timedelta(seconds=1),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=5,
    ),
    "connector": RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=2),
        maximum_attempts=4,
    ),
    "reconciliation": RetryPolicy(
        initial_interval=timedelta(seconds=5),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(minutes=5),
        maximum_attempts=6,
    ),
}

APPROVAL_WAIT = timedelta(hours=24)
RECONCILIATION_WAIT = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class WorkflowStatus:
    tenant_id: str
    case_id: str
    workflow_id: str
    state: str
    completed_stages: tuple[str, ...] = ()
    recovery_requested: bool = False
    stop_requested: bool = False


@dataclass(frozen=True, slots=True)
class CaseWorkflowResult:
    tenant_id: str
    case_id: str
    workflow_id: str
    terminal_state: str | None
    completed_stages: tuple[str, ...]
    recovered_count: int


def case_workflow_id(tenant_id: str, case_id: str) -> str:
    """Return a stable workflow identity independent of Temporal run identity."""

    if not tenant_id.strip() or not case_id.strip():
        raise ValueError("tenant_id and case_id are required for workflow identity")
    return f"reclaim.case.{tenant_id}.{case_id}"


@workflow.defn(name=CASE_WORKFLOW_NAME)
class CaseWorkflow:
    """Durable orchestration shell whose state is never business authority."""

    def __init__(self) -> None:
        self._command: CaseWorkflowCommand | None = None
        self._state = "not_started"
        self._completed_stages: list[str] = []
        self._recovery_requested = False
        self._stop_requested = False
        self._approval_received = False
        self._dependency_available = False
        self._recovery_count = 0

    @workflow.run
    async def run(self, command: CaseWorkflowCommand) -> CaseWorkflowResult:
        self._command = command
        workflow_id = case_workflow_id(command.tenant_id, command.case_id)
        self._state = "reading_authoritative_state"
        state = await self._execute(
            ACTIVITY_NAMES["read_authoritative_state"],
            command,
            RETRY_POLICIES["repository"],
        )
        self._validate_activity_result(state, command)
        self._state = str(state.get("state", command.expected_state))

        for stage in command.stages:
            if self._stop_requested:
                break
            if self._recovery_requested:
                await self._recover(command)
            result = await self._execute(
                ACTIVITY_NAMES.get(stage, f"case.{stage}"),
                command,
                RETRY_POLICIES["connector" if stage == "collect_evidence" else "repository"],
            )
            self._validate_activity_result(result, command)
            self._completed_stages.append(stage)
            self._state = str(result.get("state", self._state))

            wait_for = result.get("wait_for")
            if wait_for == "approval":
                await self._wait_for_approval(command)
            elif wait_for == "reconciliation":
                await self._wait_for_reconciliation(command)
            if result.get("terminal_state"):
                self._state = str(result["terminal_state"])
                break

        return CaseWorkflowResult(
            tenant_id=command.tenant_id,
            case_id=command.case_id,
            workflow_id=workflow_id,
            terminal_state=self._state
            if self._state
            in {
                "verified_contained",
                "verified_failed",
                "escalated_unresolved",
            }
            else None,
            completed_stages=tuple(self._completed_stages),
            recovered_count=self._recovery_count,
        )

    @workflow.signal(name="case.signal")
    async def signal(self, signal: CaseWorkflowSignal) -> None:
        """Receive approval/dependency/recovery intent without mutating business state."""

        if self._command is None:
            raise ValueError("workflow has not started")
        if (signal.tenant_id, signal.case_id) != (
            self._command.tenant_id,
            self._command.case_id,
        ):
            raise ValueError("workflow signal identity does not match the workflow")
        if signal.kind == SignalKind.APPROVAL_RECORDED:
            self._approval_received = True
        elif signal.kind == SignalKind.DEPENDENCY_AVAILABLE:
            self._dependency_available = True
        elif signal.kind == SignalKind.RECOVERY_REQUESTED:
            self._recovery_requested = True
        elif signal.kind == SignalKind.STOP_REQUESTED:
            self._stop_requested = True

    @workflow.signal(name="case.recover")
    async def recover(self, command: RecoveryCommand) -> None:
        """Request a repository-backed recovery/reconciliation activity."""

        if self._command is None:
            raise ValueError("workflow has not started")
        if (command.tenant_id, command.case_id) != (
            self._command.tenant_id,
            self._command.case_id,
        ):
            raise ValueError("recovery identity does not match the workflow")
        if command.kind == RecoveryKind.ESCALATE:
            self._stop_requested = True
        self._recovery_requested = True

    @workflow.query(name="case.status")
    def status(self) -> WorkflowStatus:
        command = self._command
        if command is None:
            return WorkflowStatus("", "", "", self._state)
        return WorkflowStatus(
            tenant_id=command.tenant_id,
            case_id=command.case_id,
            workflow_id=case_workflow_id(command.tenant_id, command.case_id),
            state=self._state,
            completed_stages=tuple(self._completed_stages),
            recovery_requested=self._recovery_requested,
            stop_requested=self._stop_requested,
        )

    async def _execute(
        self,
        activity_name: str,
        command: CaseWorkflowCommand,
        retry_policy: RetryPolicy,
    ) -> dict[str, Any]:
        timeout = ACTIVITY_TIMEOUTS["default"]
        if activity_name == ACTIVITY_NAMES["reconcile_action"]:
            timeout = ACTIVITY_TIMEOUTS["reconcile"]
        if activity_name == ACTIVITY_NAMES["escalate_unresolved"]:
            timeout = ACTIVITY_TIMEOUTS["escalate"]
        return await workflow.execute_activity(
            activity_name,
            command,
            start_to_close_timeout=timeout,
            retry_policy=retry_policy,
        )

    async def _recover(self, command: CaseWorkflowCommand) -> None:
        self._state = "recovering"
        result = await self._execute(
            ACTIVITY_NAMES["recover_authoritative_state"],
            command,
            RETRY_POLICIES["repository"],
        )
        self._validate_activity_result(result, command)
        self._state = str(result.get("state", self._state))
        self._recovery_requested = False
        self._recovery_count += 1

    async def _wait_for_approval(self, command: CaseWorkflowCommand) -> None:
        try:
            await workflow.wait_condition(
                lambda: self._approval_received,
                timeout=APPROVAL_WAIT,
            )
        except TimeoutError:
            pass
        else:
            self._approval_received = False
            return
        result = await self._execute(
            ACTIVITY_NAMES["escalate_unresolved"],
            command,
            RETRY_POLICIES["repository"],
        )
        self._validate_activity_result(result, command)
        self._state = str(result.get("terminal_state", "escalated_unresolved"))
        self._stop_requested = True

    async def _wait_for_reconciliation(self, command: CaseWorkflowCommand) -> None:
        try:
            await workflow.wait_condition(
                lambda: self._dependency_available,
                timeout=RECONCILIATION_WAIT,
            )
        except TimeoutError:
            pass
        else:
            self._dependency_available = False
            return
        result = await self._execute(
            ACTIVITY_NAMES["reconcile_action"],
            command,
            RETRY_POLICIES["reconciliation"],
        )
        self._validate_activity_result(result, command)
        self._state = str(result.get("state", self._state))

    @staticmethod
    def _validate_activity_result(result: dict[str, Any], command: CaseWorkflowCommand) -> None:
        if result.get("tenant_id") != command.tenant_id or result.get("case_id") != command.case_id:
            raise ValueError("activity result identity does not match workflow command")
        if result.get("authoritative") is not True:
            raise ValueError("workflow activity must confirm authoritative validation")
