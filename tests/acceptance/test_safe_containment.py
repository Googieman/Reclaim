"""T087 canonical US3 acceptance target.

This test intentionally prepares the complete safety path using existing US2
typed artifacts, then stops at the absent production seams.  It is strict
expected-red until T088-T100 are implemented and must not implement them here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from analysis.proposal_validator import AuthoritativeResource, canonical_action_identity
from finance.exposure import FinancialExposure
from packages.contracts.action_gateway import ActionExecutionState, VerificationResult
from packages.contracts.analysis_policy import (
    ActionType,
    PolicyResult,
    TypedActionProposal,
)
from us3_test_seams import missing_symbols


TENANT_ID = "tenant-us3-canonical"
CASE_ID = "case-us3-canonical-001"
CORRELATION_ID = "corr-us3-canonical-001"
POLICY_VERSION = "policy-us3-v1.0.0"


@dataclass(frozen=True, slots=True)
class PreparedAction:
    proposal: TypedActionProposal
    policy_result: PolicyResult
    reversible: bool
    approval_state: str
    canonical_identity: str


@dataclass(frozen=True, slots=True)
class PreparedContainmentCase:
    tenant_id: str
    case_id: str
    correlation_id: str
    validated_us2: bool
    actions: tuple[PreparedAction, ...]
    duplicate_action_request: bool
    unknown_remote_result: ActionExecutionState
    verification_result: VerificationResult
    exposure: FinancialExposure
    forbidden_actions: int
    direct_model_side_effects: int
    gateway_bypasses: int
    approval_bypasses: int
    duplicate_non_idempotent_effects: int
    model_financial_authority: bool
    expected_terminal_state: str
    expected_safety_flow: tuple[str, ...]


def _proposal(
    *,
    proposal_id: str,
    action_type: ActionType,
    target_resource: str,
    idempotency_key: str,
    analysis_id: str,
    parameters: dict[str, Any],
    requested_amount_minor: int | None = None,
    currency: str | None = None,
) -> TypedActionProposal:
    return TypedActionProposal(
        tenant_id=TENANT_ID,
        correlation_id=CORRELATION_ID,
        proposal_id=proposal_id,
        case_id=CASE_ID,
        action_type=action_type,
        target_resource=target_resource,
        parameters=parameters,
        rationale="bounded canonical US3 test proposal",
        evidence_references=("evidence-us3-session-001",),
        attribution_references=("timeline-us3-session-001",),
        requested_amount_minor=requested_amount_minor,
        currency=currency,
        idempotency_key=idempotency_key,
        analysis_id=analysis_id,
    )


def _prepared_case() -> PreparedContainmentCase:
    session_resource = AuthoritativeResource(
        resource_id="session-us3-001",
        resource_type="sessions",
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        state="active",
        connector_id="session-actions",
        evidence_references=("evidence-us3-session-001",),
        timeline_event_ids=("timeline-us3-session-001",),
    )
    revoke_first = _proposal(
        proposal_id="proposal-us3-revoke-001",
        action_type=ActionType.REVOKE_SUSPICIOUS_SESSION,
        target_resource="session-us3-001",
        idempotency_key="occurrence-us3-revoke-001",
        analysis_id="analysis-us3-001",
        parameters={"reason": "suspicious session"},
    )
    approval_gated_refund = _proposal(
        proposal_id="proposal-us3-refund-001",
        action_type=ActionType.REFUND_PAYMENT,
        target_resource="payment-us3-001",
        idempotency_key="occurrence-us3-refund-001",
        analysis_id="analysis-us3-001",
        parameters={"reason": "captured payment requires independent approval"},
        requested_amount_minor=8_000,
        currency="INR",
    )
    revoke_identity_first = canonical_action_identity(
        revoke_first,
        connector_id="session-actions",
        resource=session_resource,
    )
    exposure = FinancialExposure(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        currency="INR",
        gross_exposure_minor=50_000,
        recoverable_value_minor=50_000,
        contained_value_minor=20_000,
        legitimate_value_disrupted_minor=2_499,
        irreversible_loss_minor=0,
        remaining_exposure_minor=30_000,
        calculation_version="exposure-us3-v1.0.0",
        source_references=("timeline-us3-payment-001",),
        payment_references=("payment-us3-001",),
    )
    return PreparedContainmentCase(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        correlation_id=CORRELATION_ID,
        validated_us2=True,
        actions=(
            PreparedAction(
                proposal=revoke_first,
                policy_result=PolicyResult.ALLOW,
                reversible=True,
                approval_state="not_required",
                canonical_identity=revoke_identity_first,
            ),
            PreparedAction(
                proposal=approval_gated_refund,
                policy_result=PolicyResult.APPROVAL_REQUIRED,
                reversible=False,
                approval_state="required",
                canonical_identity="canonical-refund-us3-001",
            ),
        ),
        duplicate_action_request=True,
        unknown_remote_result=ActionExecutionState.UNKNOWN,
        verification_result=VerificationResult.INCONCLUSIVE,
        exposure=exposure,
        forbidden_actions=0,
        direct_model_side_effects=0,
        gateway_bypasses=0,
        approval_bypasses=0,
        duplicate_non_idempotent_effects=0,
        model_financial_authority=False,
        expected_terminal_state="escalated_unresolved",
        expected_safety_flow=(
            "validated_us2_proposal",
            "deterministic_policy_evaluation",
            "approval_when_required",
            "isolated_action_gateway",
            "stable_idempotent_submission",
            "unknown_reconciliation_before_retry",
            "post_action_merchant_state_verification",
            "explicit_escalation_terminal_outcome",
        ),
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Expected-red T087: canonical US3 path is prepared; missing production seams are "
        "owned by T088-T100 and listed in the assertion"
    ),
)
def test_canonical_us3_safe_containment_flow() -> None:
    case = _prepared_case()
    duplicate = _proposal(
        proposal_id="proposal-us3-revoke-duplicate",
        action_type=ActionType.REVOKE_SUSPICIOUS_SESSION,
        target_resource="session-us3-001",
        idempotency_key="occurrence-us3-revoke-duplicate",
        analysis_id="analysis-us3-002",
        parameters={"reason": "suspicious session"},
    )
    resource = AuthoritativeResource(
        resource_id="session-us3-001",
        resource_type="sessions",
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        state="active",
        connector_id="session-actions",
    )

    assert case.validated_us2 is True
    assert len(case.actions) == 2
    assert any(action.reversible for action in case.actions)
    assert any(
        action.policy_result is PolicyResult.APPROVAL_REQUIRED
        for action in case.actions
    )
    assert case.actions[0].policy_result is PolicyResult.ALLOW
    assert case.actions[1].approval_state == "required"
    assert case.duplicate_action_request is True
    assert case.actions[0].canonical_identity == canonical_action_identity(
        duplicate,
        connector_id="session-actions",
        resource=resource,
    )
    assert case.actions[0].proposal.idempotency_key != duplicate.idempotency_key
    assert case.unknown_remote_result is ActionExecutionState.UNKNOWN
    assert case.unknown_remote_result is not ActionExecutionState.VERIFIED_SUCCESS
    assert case.verification_result is VerificationResult.INCONCLUSIVE
    assert case.verification_result is not VerificationResult.VERIFIED_SUCCESS
    assert case.exposure.remaining_exposure_minor == 30_000
    assert case.forbidden_actions == 0
    assert case.direct_model_side_effects == 0
    assert case.gateway_bypasses == 0
    assert case.approval_bypasses == 0
    assert case.duplicate_non_idempotent_effects == 0
    assert case.model_financial_authority is False
    assert case.expected_safety_flow == (
        "validated_us2_proposal",
        "deterministic_policy_evaluation",
        "approval_when_required",
        "isolated_action_gateway",
        "stable_idempotent_submission",
        "unknown_reconciliation_before_retry",
        "post_action_merchant_state_verification",
        "explicit_escalation_terminal_outcome",
    )
    assert case.expected_terminal_state in {
        "verified_contained",
        "verified_failed",
        "escalated_unresolved",
    }
    assert case.expected_terminal_state == "escalated_unresolved"

    required_seams = {
        "T088": ("policy.evaluator", "evaluate_policy"),
        "T089": ("policy.tenant_configuration", "validate_tenant_policy_configuration"),
        "T090": ("approvals.service", "authorize_action"),
        "T091": ("app.audit.policy", "persist_policy_decision"),
        "T092": ("action_gateway.service", "ActionGateway"),
        "T093": ("connectors.simulators.actions", "DeterministicActionSimulator"),
        "T094": ("connectors.razorpay.actions", "validate_refund_action"),
        "T095": ("action_gateway.reconciliation", "recover_action"),
        "T096": ("action_gateway.verification", "verify_and_route"),
        "T097": ("escalation.service", "EscalationService"),
        "T098": ("cases.terminal_states", "transition_case"),
        "T099": ("api.control_plane", "submit_action"),
        "T100": ("workflows.activities.containment", "run_containment"),
    }
    missing = missing_symbols(required_seams)
    assert not missing, (
        "Canonical US3 expected-red boundary: missing production seams with exact owners: "
        + "; ".join(missing)
    )
