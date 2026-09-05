"""Regression coverage for the implemented US3 policy and action seams."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from action_gateway.service import ActionGateway, ActionGatewayError
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.events.policy_events import build_approval_event, build_policy_decision_event
from approvals.service import ApprovalError, ApprovalService
from connectors.actions.manifests import build_session_action_manifest
from connectors.razorpay.actions import validate_refund_action
from connectors.simulators.actions import (
    ActionSimulatorScenario,
    DeterministicActionSimulator,
)
from policy.evaluator import evaluate_policy
from policy.tenant_configuration import validate_tenant_policy_configuration
from policy.versions import build_policy_version, publish_policy_version

from packages.contracts.action_gateway import ActionGatewayRequest
from packages.contracts.analysis_policy import ActionType
from packages.contracts.connectors import ActionConnectorRequest

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
TENANT = "tenant-us3-runtime"


def _context(subject: str, role: str, identity_type: IdentityType = IdentityType.USER):
    return TenantAuthorizationContext(
        subject=subject,
        tenant_id=TENANT,
        roles=frozenset({role}),
        identity_type=identity_type,
        issuer="test-issuer",
    )


def _policy():
    draft = build_policy_version(
        policy_version_id="policy-us3-runtime",
        tenant_id=TENANT,
        thresholds={"min_confidence": 0.95, "max_amount_minor": 10_000},
        action_allowlist=[ActionType.REVOKE_SUSPICIOUS_SESSION.value],
        approval_rules={},
        effective_from=NOW - timedelta(minutes=1),
        effective_to=None,
        author="owner",
    )
    return publish_policy_version(
        draft, authorization_context=_context("owner", "policy-owner")
    )


def _decision():
    return evaluate_policy(
        policy_version=_policy(),
        tenant_id=TENANT,
        case_id="case-us3-runtime",
        proposal_id="proposal-us3-runtime",
        correlation_id="corr-us3-runtime",
        action=ActionType.REVOKE_SUSPICIOUS_SESSION.value,
        confidence=0.99,
        resource={
            "resource_id": "session-us3-runtime",
            "connector_id": "session-actions",
            "state": "active",
        },
        amount_minor=0,
        is_reversible=True,
        customer_impact={"class": "low"},
        evaluated_at=NOW,
    )


def test_published_policy_evaluates_deterministically_and_emits_typed_event() -> None:
    first = _decision()
    second = _decision()

    assert first == second
    assert first.result.value == "allow"
    assert build_policy_decision_event(first).event_type.value == "policy.decided"


def test_invalid_tenant_policy_change_is_bounded_and_auditable() -> None:
    result = validate_tenant_policy_configuration(
        tenant_id=TENANT,
        change="unsafe-threshold",
        thresholds={"min_confidence": 0.10},
        actor_role="policy-owner",
    )

    assert result.accepted is False
    assert result.audit_reference.startswith("policy-change:")


def test_approval_requires_distinct_approver_and_exact_store_record() -> None:
    service = ApprovalService()
    request = service.request_approval(
        tenant_id=TENANT,
        case_id="case-us3-runtime",
        proposal_id="proposal-us3-runtime",
        action_type=ActionType.REVOKE_SUSPICIOUS_SESSION.value,
        target_resource="session-us3-runtime",
        proposer_id="proposer",
        policy_version_id="policy-us3-runtime",
        correlation_id="corr-us3-runtime",
        requested_at=NOW,
    )
    approval = service.approve(
        request, approver_context=_context("approver", "approver"), approved_at=NOW
    )
    authorized = service.authorize_action(
        proposal={
            "tenant_id": TENANT,
            "case_id": "case-us3-runtime",
            "proposal_id": "proposal-us3-runtime",
            "action_type": ActionType.REVOKE_SUSPICIOUS_SESSION.value,
            "target_resource": "session-us3-runtime",
            "policy_version_id": "policy-us3-runtime",
            "proposer_id": "proposer",
        },
        approval=approval,
        now=NOW,
    )

    assert authorized.execution_authorized is True
    with pytest.raises(ApprovalError, match="stale"):
        service.revoke(approval.approval_id, tenant_id=TENANT, expected_version=0)
    assert build_approval_event(approval).event_type.value == "approval.recorded"


def test_action_gateway_requires_service_identity_and_preserves_idempotency() -> None:
    simulator = DeterministicActionSimulator(
        build_session_action_manifest(TENANT),
        scenario=ActionSimulatorScenario.COMPLETED,
    )
    decision = _decision()
    request = ActionGatewayRequest(
        tenant_id=TENANT,
        correlation_id="corr-us3-runtime",
        case_id="case-us3-runtime",
        proposal_id="proposal-us3-runtime",
        action_type=ActionType.REVOKE_SUSPICIOUS_SESSION,
        connector_id="session-actions",
        operation="revoke_suspicious_session",
        target_resource="session-us3-runtime",
        parameters={"reason": "confirmed"},
        policy_decision_id=decision.decision_id,
        policy_version_id=decision.policy_version_id,
        idempotency_key="action-us3-runtime",
        causation_id="proposal-us3-runtime",
        request_checksum="checksum",
        requested_at=NOW,
    )
    gateway = ActionGateway(connectors={"session-actions": simulator})
    resource = {
        "tenant_id": TENANT,
        "case_id": "case-us3-runtime",
        "resource_id": "session-us3-runtime",
        "resource_type": "sessions",
        "state": "active",
    }
    with pytest.raises(ActionGatewayError, match="service identity"):
        gateway.submit(
            request, policy_decision=decision, authoritative_resource=resource
        )
    response = gateway.submit(
        request,
        policy_decision=decision,
        authoritative_resource=resource,
        authorization_context=_context("gateway", "service", IdentityType.SERVICE),
    )

    assert response.state.value == "completed"
    assert (
        response.remote_reference
        == simulator.execute(
            ActionConnectorRequest(
                tenant_id=TENANT,
                correlation_id="corr-us3-runtime",
                case_id="case-us3-runtime",
                proposal_id="proposal-us3-runtime",
                connector_id="session-actions",
                operation="revoke_suspicious_session",
                target_resource="session-us3-runtime",
                parameters={"reason": "confirmed"},
                idempotency_key="action-us3-runtime",
                requested_at=NOW,
            )
        ).remote_reference
    )


def test_action_simulator_exposes_controlled_outcomes_and_refund_stays_bounded() -> (
    None
):
    for scenario in ActionSimulatorScenario:
        simulator = DeterministicActionSimulator(
            build_session_action_manifest(TENANT), scenario=scenario
        )
        response = simulator.execute(
            ActionConnectorRequest(
                tenant_id=TENANT,
                correlation_id="corr-us3-outcome",
                case_id="case-us3-runtime",
                proposal_id=f"proposal-{scenario.value}",
                connector_id="session-actions",
                operation="revoke_suspicious_session",
                target_resource="session-us3-runtime",
                parameters={"reason": "confirmed"},
                idempotency_key=f"idempotency-{scenario.value}",
                requested_at=NOW,
            )
        )
        assert response.result.value == scenario.value

    result = validate_refund_action(
        {
            "tenant_id": TENANT,
            "case_id": "case-us3-runtime",
            "payment_id": "payment-us3-runtime",
            "state": "captured",
            "captured": True,
            "amount_minor": 10_000,
            "reimbursed_minor": 2_000,
            "requested_amount_minor": 8_000,
            "currency": "INR",
            "original_payment_source": "source-us3-runtime",
            "refund_destination": "attacker-controlled-account",
            "policy_version_id": "policy-us3-runtime",
            "proposal_id": "proposal-us3-runtime",
        }
    )
    assert result.allowed is False
