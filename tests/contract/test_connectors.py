from datetime import datetime, timezone

from packages.contracts.connectors import (
    ActionConnectorResponse,
    ActionConnectorResult,
    ConnectorFailureState,
    EvidenceRequest,
    EvidenceResponse,
)


def test_evidence_contract_preserves_provenance_and_partial_state() -> None:
    response = EvidenceResponse(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        case_id="case-1",
        connector_id="sessions",
        source_identity="merchant-session-store",
        resource_type="sessions",
        observed_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        collected_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        completeness="partial",
        raw_artifact_reference="minio://artifact-1",
        raw_checksum="sha256:raw",
        normalized_facts=[{"session_id": "s-1"}],
        connector_status="partial",
    )
    assert response.failure_state is ConnectorFailureState.PARTIAL
    assert response.untrusted is True


def test_unknown_action_result_requires_reconciliation() -> None:
    response = ActionConnectorResponse(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        case_id="case-1",
        proposal_id="proposal-1",
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        result=ActionConnectorResult.UNKNOWN,
        idempotency_key="action-1",
    )
    assert response.reconciliation_required is True
    assert response.failure_state is ConnectorFailureState.UNKNOWN_RESULT


def test_evidence_request_is_tenant_and_case_scoped() -> None:
    request = EvidenceRequest(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        case_id="case-1",
        connector_id="payments",
        resource_type="payments",
        requested_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    assert request.operation == "read"
