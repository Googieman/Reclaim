"""Unit checks for the Temporal/PostgreSQL authority split."""

from datetime import timedelta

import pytest
from workflows.case_workflow import (
    ACTIVITY_NAMES,
    CASE_WORKFLOW_NAME,
    RETRY_POLICIES,
    case_workflow_id,
)
from workflows.commands import CaseWorkflowCommand, RecoveryCommand, RecoveryKind


def test_workflow_identity_and_command_are_tenant_scoped() -> None:
    command = CaseWorkflowCommand(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        command_id="cmd-1",
    )

    assert case_workflow_id("tenant-a", "case-1") == "reclaim.case.tenant-a.case-1"
    assert command.stages


def test_workflow_retries_are_bounded_and_separate_for_reconciliation() -> None:
    assert RETRY_POLICIES["repository"].maximum_attempts == 5
    assert RETRY_POLICIES["reconciliation"].maximum_attempts == 6
    assert RETRY_POLICIES["reconciliation"].initial_interval == timedelta(seconds=5)
    assert CASE_WORKFLOW_NAME == "reclaim.case.v1"
    assert ACTIVITY_NAMES["read_authoritative_state"] == "case.read_authoritative_state"


def test_recovery_command_requires_identity_and_reason() -> None:
    recovery = RecoveryCommand(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        command_id="recovery-1",
        kind=RecoveryKind.RECONCILE,
        reason="worker restarted",
    )
    assert recovery.kind is RecoveryKind.RECONCILE
    with pytest.raises(ValueError, match="reason"):
        RecoveryCommand(
            tenant_id="tenant-a",
            case_id="case-1",
            correlation_id="corr-1",
            command_id="recovery-2",
            kind=RecoveryKind.RESUME,
            reason=" ",
        )
