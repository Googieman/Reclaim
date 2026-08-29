from datetime import datetime, timezone

from packages.contracts.action_gateway import (
    ActionExecutionState,
    ActionGatewayRequest,
    ActionGatewayResponse,
    VerificationRequest,
    VerificationResponse,
    VerificationResult,
)


def test_gateway_request_contains_policy_approval_idempotency_and_checksum() -> None:
    request = ActionGatewayRequest(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        case_id="case-1",
        proposal_id="proposal-1",
        action_type="revoke_suspicious_session",
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        target_resource="session-1",
        policy_decision_id="decision-1",
        policy_version_id="policy-1",
        approval_id=None,
        idempotency_key="action-key-1",
        causation_id="proposal-1",
        request_checksum="sha256:request",
        requested_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    assert request.idempotency_key == "action-key-1"


def test_unknown_is_first_class_and_verification_is_not_implicit_success() -> None:
    response = ActionGatewayResponse(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        execution_id="execution-1",
        proposal_id="proposal-1",
        state=ActionExecutionState.UNKNOWN,
        connector_result="unknown",
        idempotency_key="action-key-1",
        audit_reference="audit-1",
    )
    verification = VerificationResponse(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        verification_id="verification-1",
        execution_id="execution-1",
        observed_resource_state="not_observed",
        verifier_source="session-store",
        result=VerificationResult.INCONCLUSIVE,
        verified_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    assert response.reconciliation_required is True
    assert verification.result == "inconclusive"

    request = VerificationRequest(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        execution_id="execution-1",
        case_id="case-1",
        target_resource="session-1",
        requested_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    assert request.requested_at.tzinfo == timezone.utc
