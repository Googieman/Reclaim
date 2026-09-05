"""Deterministic T095/T101 recovery coverage; no live merchant system is used."""

from __future__ import annotations

from datetime import UTC, datetime

from action_gateway.idempotency import (
    InMemoryActionExecutionStore,
    derive_action_idempotency_key,
)
from action_gateway.service import ActionGateway
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from connectors.actions.manifests import build_session_action_manifest
from packages.contracts.action_gateway import ActionExecutionState, ActionGatewayRequest
from packages.contracts.analysis_policy import PolicyDecision, PolicyResult
from packages.contracts.connectors import ActionConnectorResponse, ActionConnectorResult


TENANT = "tenant-us3-lifecycle"
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class CountingConnector:
    manifest = build_session_action_manifest(TENANT)

    def __init__(
        self, result: ActionConnectorResult = ActionConnectorResult.COMPLETED
    ) -> None:
        self.result = result
        self.calls = 0

    def execute(
        self, request: ActionGatewayRequest, *, credentials=None
    ) -> ActionConnectorResponse:
        del credentials
        self.calls += 1
        return ActionConnectorResponse(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            case_id=request.case_id,
            proposal_id=request.proposal_id,
            connector_id=request.connector_id,
            operation=request.operation,
            result=self.result,
            remote_reference="remote-us3-lifecycle"
            if self.result is not ActionConnectorResult.UNKNOWN
            else None,
            idempotency_key=request.idempotency_key,
        )


def _context() -> TenantAuthorizationContext:
    return TenantAuthorizationContext(
        subject="gateway-service",
        tenant_id=TENANT,
        roles=frozenset({"service"}),
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )


def _resource() -> dict[str, str]:
    return {
        "tenant_id": TENANT,
        "case_id": "case-us3-lifecycle",
        "resource_id": "session-us3-lifecycle",
        "resource_type": "sessions",
        "connector_id": "session-actions",
        "state": "active",
    }


def _request(proposal_id: str = "proposal-us3-lifecycle") -> ActionGatewayRequest:
    resource = _resource()
    canonical = derive_action_idempotency_key(
        {
            "tenant_id": TENANT,
            "case_id": resource["case_id"],
            "action_type": "revoke_suspicious_session",
            "parameters": {"reason": "confirmed"},
            "requested_amount_minor": None,
            "currency": None,
            "schema_version": "1.0.0",
        },
        connector_id="session-actions",
        authoritative_resource=resource,
    )
    return ActionGatewayRequest(
        tenant_id=TENANT,
        correlation_id="corr-us3-lifecycle",
        case_id=resource["case_id"],
        proposal_id=proposal_id,
        action_type="revoke_suspicious_session",
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        target_resource=resource["resource_id"],
        parameters={"reason": "confirmed"},
        policy_decision_id="decision-us3-lifecycle",
        policy_version_id="policy-us3-lifecycle",
        idempotency_key=canonical,
        causation_id=proposal_id,
        request_checksum="checksum-us3-lifecycle",
        requested_at=NOW,
    )


def _decision(proposal_id: str) -> PolicyDecision:
    return PolicyDecision(
        tenant_id=TENANT,
        correlation_id="corr-us3-lifecycle",
        decision_id="decision-us3-lifecycle",
        case_id="case-us3-lifecycle",
        proposal_id=proposal_id,
        policy_version_id="policy-us3-lifecycle",
        result=PolicyResult.ALLOW,
        evaluated_conditions={"deterministic": True},
        evaluator_version="policy-evaluator-v1.0.0",
        decided_at=NOW,
    )


def test_duplicate_semantic_submission_converges_without_second_connector_call() -> (
    None
):
    connector = CountingConnector()
    store = InMemoryActionExecutionStore()
    gateway = ActionGateway(
        connectors={"session-actions": connector}, execution_store=store
    )
    first = _request()
    second = _request("proposal-us3-lifecycle-duplicate")

    first_response = gateway.submit(
        first,
        policy_decision=_decision(first.proposal_id),
        authoritative_resource=_resource(),
        authorization_context=_context(),
    )
    second_response = gateway.submit(
        second,
        policy_decision=_decision(second.proposal_id),
        authoritative_resource=_resource(),
        authorization_context=_context(),
    )

    assert first_response.state is ActionExecutionState.COMPLETED
    assert second_response.execution_id == first_response.execution_id
    assert second_response.proposal_id == first_response.proposal_id
    assert connector.calls == 1
    record = store.get(tenant_id=TENANT, canonical_action_id=first.idempotency_key)
    assert record is not None
    assert record.attempt_count == 1
    assert record.correlation_id == first.correlation_id


def test_gateway_exception_is_persisted_as_unknown_and_never_blindly_retried() -> None:
    connector = CountingConnector(ActionConnectorResult.UNKNOWN)
    store = InMemoryActionExecutionStore()
    gateway = ActionGateway(
        connectors={"session-actions": connector}, execution_store=store
    )
    request = _request()
    response = gateway.submit(
        request,
        policy_decision=_decision(request.proposal_id),
        authoritative_resource=_resource(),
        authorization_context=_context(),
    )
    duplicate = gateway.submit(
        request,
        policy_decision=_decision(request.proposal_id),
        authoritative_resource=_resource(),
        authorization_context=_context(),
    )

    assert response.state is ActionExecutionState.UNKNOWN
    assert response.reconciliation_required is True
    assert duplicate.state is ActionExecutionState.UNKNOWN
    assert connector.calls == 1
