"""T082 Action Gateway state-machine contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from packages.contracts.action_gateway import (
    ActionExecutionState,
    ActionGatewayResponse,
    VerificationResponse,
    VerificationResult,
)
from packages.contracts.connectors import ActionConnectorResponse, ActionConnectorResult
from us3_test_seams import require_symbol


def test_repository_action_states_are_exact_and_include_unknown() -> None:
    assert tuple(state.value for state in ActionExecutionState) == (
        "not_started",
        "received",
        "validated",
        "pending_remote",
        "completed",
        "failed",
        "unknown",
        "reconciling",
        "reconciled",
        "verifying",
        "verified_success",
        "verified_failure",
        "escalated",
    )


def test_gateway_response_retains_state_identity_and_audit_fields() -> None:
    response = ActionGatewayResponse(
        tenant_id="tenant-us3-gateway",
        correlation_id="corr-us3-gateway-001",
        execution_id="execution-us3-001",
        proposal_id="proposal-us3-001",
        state=ActionExecutionState.VALIDATED,
        connector_result="accepted",
        idempotency_key="canonical-action-us3-001",
        verification_required=True,
        audit_reference="audit-us3-001",
    )

    assert response.state is ActionExecutionState.VALIDATED
    assert response.proposal_id == "proposal-us3-001"
    assert response.idempotency_key == "canonical-action-us3-001"
    assert response.verification_required is True
    assert response.audit_reference == "audit-us3-001"


def test_unknown_is_not_success_and_requires_reconciliation() -> None:
    gateway_response = ActionGatewayResponse(
        tenant_id="tenant-us3-gateway",
        correlation_id="corr-us3-gateway-001",
        execution_id="execution-us3-unknown",
        proposal_id="proposal-us3-001",
        state=ActionExecutionState.UNKNOWN,
        connector_result="unknown",
        idempotency_key="canonical-action-us3-001",
        audit_reference="audit-us3-unknown",
    )
    connector_response = ActionConnectorResponse(
        tenant_id="tenant-us3-gateway",
        correlation_id="corr-us3-gateway-001",
        case_id="case-us3-gateway-001",
        proposal_id="proposal-us3-001",
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        result=ActionConnectorResult.UNKNOWN,
        idempotency_key="canonical-action-us3-001",
    )

    assert gateway_response.state is ActionExecutionState.UNKNOWN
    assert gateway_response.state is not ActionExecutionState.VERIFIED_SUCCESS
    assert gateway_response.reconciliation_required is True
    assert connector_response.reconciliation_required is True
    assert connector_response.failure_state.value == "unknown_result"


def test_inconclusive_verification_is_not_a_terminal_success() -> None:
    verification = VerificationResponse(
        tenant_id="tenant-us3-gateway",
        correlation_id="corr-us3-gateway-001",
        verification_id="verification-us3-001",
        execution_id="execution-us3-001",
        observed_resource_state="not_observed",
        verifier_source="merchant-session-store",
        result=VerificationResult.INCONCLUSIVE,
        evidence_references=("evidence-us3-001",),
        verified_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )

    assert verification.result is VerificationResult.INCONCLUSIVE
    assert verification.result is not VerificationResult.VERIFIED_SUCCESS
    assert verification.evidence_references == ("evidence-us3-001",)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Expected-red owners T092/T095/T096/T097: gateway transition, reconciliation, "
        "verification, and escalation implementations are not started"
    ),
)
def test_state_machine_rejects_invalid_transitions_and_requires_reconciliation_verification() -> (
    None
):
    state_machine = require_symbol(
        "action_gateway.state_machine",
        "ActionGatewayStateMachine",
        task="T082 -> T092/T095/T096/T097",
    )
    machine = state_machine()

    with pytest.raises(ValueError):
        machine.transition(
            ActionExecutionState.NOT_STARTED, ActionExecutionState.COMPLETED
        )
    with pytest.raises(ValueError):
        machine.transition(
            ActionExecutionState.UNKNOWN, ActionExecutionState.PENDING_REMOTE
        )
    with pytest.raises(ValueError):
        machine.transition(
            ActionExecutionState.UNKNOWN, ActionExecutionState.VERIFIED_SUCCESS
        )
    with pytest.raises(ValueError):
        machine.transition(
            ActionExecutionState.VERIFYING, ActionExecutionState.COMPLETED
        )
    assert machine.transition(
        ActionExecutionState.UNKNOWN, ActionExecutionState.RECONCILING
    )
    assert machine.transition(
        ActionExecutionState.RECONCILING, ActionExecutionState.ESCALATED
    )
