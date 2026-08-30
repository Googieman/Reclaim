"""Typed commands and signals exchanged with the case workflow.

The workflow carries identity and orchestration intent only.  Activities are the
only place where repository-backed business validation may happen.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.db.tenant_context import require_tenant_id


class WorkflowCommandKind(StrEnum):
    START = "start"
    RESUME = "resume"
    RECOVER = "recover"


class SignalKind(StrEnum):
    APPROVAL_RECORDED = "approval_recorded"
    DEPENDENCY_AVAILABLE = "dependency_available"
    RECOVERY_REQUESTED = "recovery_requested"
    STOP_REQUESTED = "stop_requested"


class RecoveryKind(StrEnum):
    RESUME = "resume"
    RECONCILE = "reconcile"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class CaseWorkflowCommand:
    """Start/resume intent for one tenant-scoped case workflow."""

    tenant_id: str
    case_id: str
    correlation_id: str
    command_id: str
    kind: WorkflowCommandKind = WorkflowCommandKind.START
    expected_state: str = "intake_received"
    stages: tuple[str, ...] = (
        "collect_evidence",
        "rebuild_timeline",
        "analyze_case",
        "evaluate_policy",
        "execute_actions",
        "verify_case",
    )
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", require_tenant_id(self.tenant_id))
        for name, value in (
            ("case_id", self.case_id),
            ("correlation_id", self.correlation_id),
            ("command_id", self.command_id),
            ("expected_state", self.expected_state),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required")
        if not self.stages:
            raise ValueError("workflow must contain at least one activity stage")
        if any(not stage.strip() for stage in self.stages):
            raise ValueError("workflow stages cannot be blank")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class RecoveryCommand:
    """Operator/service request to recover a workflow from authoritative state."""

    tenant_id: str
    case_id: str
    correlation_id: str
    command_id: str
    kind: RecoveryKind
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", require_tenant_id(self.tenant_id))
        for name, value in (
            ("case_id", self.case_id),
            ("correlation_id", self.correlation_id),
            ("command_id", self.command_id),
            ("reason", self.reason),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required")


@dataclass(frozen=True, slots=True)
class CaseWorkflowSignal:
    """Signal payload that can wake a waiting workflow without changing truth."""

    tenant_id: str
    case_id: str
    correlation_id: str
    kind: SignalKind
    reference: str | None = None
    payload: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", require_tenant_id(self.tenant_id))
        for name, value in (
            ("case_id", self.case_id),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required")
        object.__setattr__(self, "payload", dict(self.payload))
