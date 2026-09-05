"""Fail-closed action/connector qualification hardening tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from action_gateway.service import ActionGateway, ActionGatewayError
from action_gateway.idempotency import derive_action_idempotency_key
from app.auth.oidc import IdentityType, TenantAuthorizationContext
from app.config import Settings
from app.control_plane.tenant_config import TenantConfiguration
from connectors.actions.manifests import build_session_action_manifest
from connectors.razorpay.actions import (
    build_razorpay_test_mode_action_manifest,
    validate_refund_action,
)
from packages.contracts.action_gateway import ActionExecutionState, ActionGatewayRequest
from packages.contracts.analysis_policy import ActionType, PolicyDecision, PolicyResult
from packages.contracts.connectors import (
    ActionConnectorResponse,
    ActionConnectorResult,
    ConnectorMode,
)
from us3_test_seams import require_symbol


TENANT = "tenant-action-hardening"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


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
        "case_id": "case-action-hardening",
        "resource_id": "session-action-hardening",
        "resource_type": "sessions",
        "connector_id": "session-actions",
        "state": "active",
    }


def _request(*, connector_id: str = "session-actions") -> ActionGatewayRequest:
    resource = _resource()
    canonical = derive_action_idempotency_key(
        {
            "tenant_id": TENANT,
            "case_id": resource["case_id"],
            "action_type": ActionType.REVOKE_SUSPICIOUS_SESSION.value,
            "parameters": {"reason": "confirmed"},
            "requested_amount_minor": None,
            "currency": None,
            "schema_version": "1.0.0",
        },
        connector_id=connector_id,
        authoritative_resource=resource,
    )
    return ActionGatewayRequest(
        tenant_id=TENANT,
        correlation_id="corr-action-hardening",
        case_id="case-action-hardening",
        proposal_id="proposal-action-hardening",
        action_type=ActionType.REVOKE_SUSPICIOUS_SESSION,
        connector_id=connector_id,
        operation="revoke_suspicious_session",
        target_resource="session-action-hardening",
        parameters={"reason": "confirmed"},
        policy_decision_id="decision-action-hardening",
        policy_version_id="policy-action-hardening",
        idempotency_key=canonical,
        causation_id="proposal-action-hardening",
        request_checksum="sha256:action-hardening",
        requested_at=NOW,
    )


def _decision() -> PolicyDecision:
    return PolicyDecision(
        tenant_id=TENANT,
        correlation_id="corr-action-hardening",
        decision_id="decision-action-hardening",
        case_id="case-action-hardening",
        proposal_id="proposal-action-hardening",
        policy_version_id="policy-action-hardening",
        result=PolicyResult.ALLOW,
        evaluated_conditions={"deterministic": True},
        evaluator_version="policy-evaluator-v1.0.0",
        decided_at=NOW,
    )


class _Connector:
    def __init__(self, manifest: Any, *, wrong_scope: bool = False) -> None:
        self.manifest = manifest
        self.wrong_scope = wrong_scope
        self.calls = 0

    def execute(self, request: ActionGatewayRequest, *, credentials=None) -> ActionConnectorResponse:
        del credentials
        self.calls += 1
        return ActionConnectorResponse(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            case_id="case-other" if self.wrong_scope else request.case_id,
            proposal_id=request.proposal_id,
            connector_id=request.connector_id,
            operation=request.operation,
            result=ActionConnectorResult.COMPLETED,
            remote_reference="remote-action-hardening",
            idempotency_key=request.idempotency_key,
        )


class _SecretStore:
    def __init__(self) -> None:
        self.reads = 0

    def read_action_connector_secret(self, **_: object) -> dict[str, str]:
        self.reads += 1
        return {"credential": "must-not-be-read-for-simulator"}


def _controls(**overrides: object) -> Any:
    controls = require_symbol(
        "action_gateway.controls",
        "TenantActionControls",
        task="Phase 4 action qualification hardening",
    )
    values: dict[str, object] = {
        "tenant_id": TENANT,
        "connector_allowlist": frozenset({"session-actions"}),
        "action_allowlist": frozenset({"revoke_suspicious_session"}),
    }
    values.update(overrides)
    return controls(**values)


def test_live_action_manifest_is_not_qualified_by_gateway() -> None:
    connector = _Connector(
        build_session_action_manifest(TENANT, mode=ConnectorMode.LIVE)
    )
    result = ActionGateway(connectors={"session-actions": connector}).validate(
        _request(),
        policy_decision=_decision(),
        authoritative_resource=_resource(),
        authorization_context=_context(),
    )

    assert result.valid is False
    assert any("live" in reason.lower() or "qualif" in reason.lower() for reason in result.reasons)


def test_gateway_validation_rejects_untyped_proposal_without_attribute_error() -> None:
    result = ActionGateway(connectors={}).validate({"connector_id": "session-actions"})

    assert result.valid is False
    assert "ActionGatewayRequest" in " ".join(result.reasons)


@pytest.mark.parametrize("switch", ("emergency_disabled", "circuit_breaker_open"))
def test_tenant_action_safety_switches_block_before_connector_call(switch: str) -> None:
    connector = _Connector(build_session_action_manifest(TENANT))
    gateway = ActionGateway(
        connectors={"session-actions": connector},
        tenant_controls={TENANT: _controls(**{switch: True})},
    )

    with pytest.raises(ActionGatewayError, match="disable|circuit"):
        gateway.submit(
            _request(),
            policy_decision=_decision(),
            authoritative_resource=_resource(),
            authorization_context=_context(),
        )
    assert connector.calls == 0


def test_tenant_connector_and_action_allowlists_are_enforced() -> None:
    connector = _Connector(build_session_action_manifest(TENANT))
    gateway = ActionGateway(
        connectors={"session-actions": connector},
        tenant_controls={
            TENANT: _controls(
                connector_allowlist=frozenset(),
                action_allowlist=frozenset(),
            )
        },
    )

    result = gateway.validate(
        _request(),
        policy_decision=_decision(),
        authoritative_resource=_resource(),
        authorization_context=_context(),
    )

    assert result.valid is False
    assert any("allowlist" in reason.lower() for reason in result.reasons)


def test_service_identity_without_gateway_service_role_is_rejected() -> None:
    connector = _Connector(build_session_action_manifest(TENANT))
    gateway = ActionGateway(connectors={"session-actions": connector})
    context = TenantAuthorizationContext(
        subject="wrong-service",
        tenant_id=TENANT,
        roles=frozenset({"reviewer"}),
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )

    result = gateway.validate(
        _request(),
        policy_decision=_decision(),
        authoritative_resource=_resource(),
        authorization_context=context,
    )

    assert result.valid is False
    assert any("service role" in reason.lower() for reason in result.reasons)


def test_simulator_submission_does_not_request_action_credentials() -> None:
    connector = _Connector(build_session_action_manifest(TENANT))
    secrets = _SecretStore()
    response = ActionGateway(
        connectors={"session-actions": connector},
        secret_store=secrets,
    ).submit(
        _request(),
        policy_decision=_decision(),
        authoritative_resource=_resource(),
        authorization_context=_context(),
    )

    assert response.state is ActionExecutionState.COMPLETED
    assert secrets.reads == 0


def test_malformed_connector_response_becomes_unknown_and_requires_reconciliation() -> None:
    connector = _Connector(build_session_action_manifest(TENANT), wrong_scope=True)
    store = require_symbol(
        "action_gateway.idempotency",
        "InMemoryActionExecutionStore",
        task="Phase 4 action qualification hardening",
    )()
    gateway = ActionGateway(
        connectors={"session-actions": connector},
        execution_store=store,
    )

    response = gateway.submit(
        _request(),
        policy_decision=_decision(),
        authoritative_resource=_resource(),
        authorization_context=_context(),
    )

    assert response.state is ActionExecutionState.UNKNOWN
    assert response.reconciliation_required is True
    assert connector.calls == 1


def test_refund_validation_requires_authoritative_payment_record() -> None:
    result = validate_refund_action(
        {
            "tenant_id": TENANT,
            "case_id": "case-action-hardening",
            "payment_id": "payment-action-hardening",
            "state": "captured",
            "captured": True,
            "amount_minor": 1_000,
            "reimbursed_minor": 0,
            "requested_amount_minor": 100,
            "currency": "INR",
            "original_payment_source": "source-action-hardening",
            "policy_version_id": "policy-action-hardening",
            "proposal_id": "proposal-action-hardening",
            "provider_mode": "test",
        }
    )

    assert result.allowed is False
    assert "authoritative" in result.reason.lower()


def test_refund_request_cannot_override_authoritative_payment_amount_or_source() -> None:
    result = validate_refund_action(
        {
            "tenant_id": TENANT,
            "case_id": "case-action-hardening",
            "payment_id": "payment-action-hardening",
            "state": "captured",
            "captured": True,
            "amount_minor": 9_999,
            "reimbursed_minor": 0,
            "requested_amount_minor": 100,
            "currency": "INR",
            "original_payment_source": "source-attacker",
            "policy_version_id": "policy-action-hardening",
            "proposal_id": "proposal-action-hardening",
            "provider_mode": "test",
            "authoritative_payment": {
                "tenant_id": TENANT,
                "case_id": "case-action-hardening",
                "payment_id": "payment-action-hardening",
                "state": "captured",
                "amount_minor": 1_000,
                "reimbursed_minor": 0,
                "currency": "INR",
                "payment_source": "source-authoritative",
            },
        }
    )

    assert result.allowed is False
    assert "authoritative payment" in result.reason.lower()


def test_razorpay_test_mode_action_manifest_rejects_live_mode() -> None:
    with pytest.raises(ValueError, match="live|Test Mode|qualification"):
        build_razorpay_test_mode_action_manifest(TENANT, mode=ConnectorMode.LIVE)


@pytest.mark.parametrize("field", ("live_actions_enabled", "live_financial_actions_enabled"))
def test_unqualified_live_action_settings_fail_closed(field: str) -> None:
    with pytest.raises(ValueError, match="live|qualif"):
        TenantConfiguration(
            tenant_id=TENANT,
            connector_ids=frozenset({"session-actions"}),
            policy_version_id="policy-action-hardening",
            **{field: True},
        )

    with pytest.raises(ValueError, match="live|qualif"):
        Settings(_env_file=None, **{field: True})


def test_tenant_parameter_and_amount_limits_are_enforced_before_connector_call() -> None:
    connector = _Connector(build_session_action_manifest(TENANT))
    gateway = ActionGateway(
        connectors={"session-actions": connector},
        tenant_controls={
            TENANT: _controls(max_parameter_bytes=8, max_amount_minor=100)
        },
    )
    result = gateway.validate(
        _request(),
        policy_decision=_decision(),
        authoritative_resource=_resource(),
        authorization_context=_context(),
    )

    assert result.valid is False
    assert "tenant limit" in " ".join(result.reasons)


def test_tenant_action_controls_reject_non_frozen_allowlist_shapes() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        _controls(action_allowlist=[ActionType.REVOKE_SUSPICIOUS_SESSION.value])
