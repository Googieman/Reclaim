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
    canonical_action_identity,
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
    rationale: str = "The authoritative malicious activity requires review.",
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
        rationale=rationale,
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


def test_same_tenant_resource_from_another_connector_is_rejected() -> None:
    mismatched = replace(
        resource("order-t075", "orders", "timeline-order-t075"),
        connector_id="other-action-connector",
    )

    result = validate(proposal(), context(target_resource=mismatched))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("connector" in reason for reason in result.reasons)


def test_forged_typed_proposal_cannot_bypass_connector_resource_binding() -> None:
    mismatched = replace(
        resource("order-t075", "orders", "timeline-order-t075"),
        connector_id="other-action-connector",
    )
    forged = TypedActionProposal.model_construct(**proposal().model_dump())

    result = validate(forged, context(target_resource=mismatched))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("connector" in reason for reason in result.reasons)


def test_model_supplied_connector_metadata_is_not_authoritative() -> None:
    forged_values = proposal().model_dump()
    forged = TypedActionProposal.model_construct(**forged_values)
    forged.__dict__["connector_id"] = "other-action-connector"

    result = validate(forged)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("unsupported fields" in reason for reason in result.reasons)


def test_payment_from_another_connector_is_rejected() -> None:
    payment = resource(
        "payment-t075",
        "payments",
        "timeline-payment-t075",
        attributes={
            "state": "captured",
            "amount_minor": 10_000,
            "currency": "INR",
            "payment_source": "source-t075",
        },
    )
    mismatched = replace(payment, connector_id="other-payment-connector")
    state = context(
        target="payment-t075",
        timeline_event_id="timeline-payment-t075",
        target_resource=mismatched,
    )

    result = validate(
        proposal(
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-t075",
            attribution_references=("timeline-payment-t075",),
            requested_amount_minor=1_000,
            currency="INR",
        ),
        state,
    )

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("connector" in reason for reason in result.reasons)


def test_refund_to_source_with_wrong_connector_is_rejected() -> None:
    payment = resource(
        "payment-t075",
        "payments",
        "timeline-payment-t075",
        attributes={
            "state": "captured",
            "amount_minor": 10_000,
            "currency": "INR",
            "payment_source": "source-t075",
        },
    )
    state = context(
        target="payment-t075",
        timeline_event_id="timeline-payment-t075",
        target_resource=replace(payment, connector_id="other-payment-connector"),
    )

    result = validate(
        proposal(
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-t075",
            attribution_references=("timeline-payment-t075",),
            requested_amount_minor=1_000,
            currency="INR",
        ),
        state,
    )

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("connector" in reason for reason in result.reasons)


def test_same_external_resource_id_under_two_connectors_is_ambiguous() -> None:
    first = resource("order-shared-t075", "orders", "timeline-order-t075")
    second = replace(first, connector_id="other-action-connector")
    state = replace(
        context(target="order-shared-t075", target_resource=first),
        resources=(first, second),
    )

    result = validate(proposal(target_resource="order-shared-t075"), state)

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("ambiguous" in reason for reason in result.reasons)


def test_action_requiring_connector_fails_closed_without_resource_binding() -> None:
    unbound = replace(resource("order-t075", "orders", "timeline-order-t075"), connector_id=None)

    result = validate(proposal(), context(target_resource=unbound))

    assert result.status is ProposalValidationStatus.REJECTED
    assert any("no authoritative connector binding" in reason for reason in result.reasons)


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


def test_supplied_idempotency_key_is_advisory_provenance_only() -> None:
    state = context(existing_idempotency_keys={"idempotency-t075": "different-action-identity"})

    result = validate(proposal(), state)

    assert result.status is ProposalValidationStatus.VALID
    assert result.supplied_idempotency_key == "idempotency-t075"
    assert result.canonical_action_identity


def test_semantically_identical_actions_share_canonical_identity_across_keys() -> None:
    first = validate(proposal(proposal_id="proposal-key-a", idempotency_key="key-a"))
    second = validate(proposal(proposal_id="proposal-key-b", idempotency_key="key-b"))

    assert first.status is ProposalValidationStatus.VALID
    assert second.status is ProposalValidationStatus.VALID
    assert first.canonical_action_identity == second.canonical_action_identity
    assert first.canonical_action_identity not in {"key-a", "key-b"}


def test_major_2_reproduction_converges_across_analysis_ids_and_supplied_keys() -> None:
    first = validate(
        proposal(
            proposal_id="proposal-analysis-a",
            analysis_id="analysis-a",
            idempotency_key="alpha",
        ),
        replace(context(), analysis_id="analysis-a", provider="provider-a", model="model-a"),
    )
    second = validate(
        proposal(
            proposal_id="proposal-analysis-b",
            analysis_id="analysis-b",
            idempotency_key="beta",
        ),
        replace(context(), analysis_id="analysis-b", provider="provider-b", model="model-b"),
    )

    assert first.status is ProposalValidationStatus.VALID
    assert second.status is ProposalValidationStatus.VALID
    assert first.canonical_action_identity == second.canonical_action_identity
    assert first.supplied_idempotency_key == "alpha"
    assert second.supplied_idempotency_key == "beta"


def test_canonical_identity_excludes_provenance_and_evidence_metadata() -> None:
    first = canonical_action_identity(
        proposal(
            proposal_id="proposal-provenance-a",
            correlation_id="correlation-a",
            analysis_id="analysis-a",
            idempotency_key="supplied-a",
        ),
        connector_id="action-connector-t075",
        resource=resource("order-t075", "orders", "timeline-order-t075"),
    )
    second = canonical_action_identity(
        proposal(
            proposal_id="proposal-provenance-b",
            correlation_id="correlation-b",
            analysis_id="analysis-b",
            idempotency_key="supplied-b",
            rationale="A different provenance explanation.",
            evidence_references=(EVIDENCE_ID, "evidence-other"),
            attribution_references=("timeline-order-t075", "timeline-other"),
        ),
        connector_id="action-connector-t075",
        resource=resource("order-t075", "orders", "timeline-order-t075"),
    )

    assert first == second


def test_canonical_identity_ignores_validation_version() -> None:
    first = ProposalValidator(validation_version="validator-a").validate(proposal(), context())
    second = ProposalValidator(validation_version="validator-b").validate(
        proposal(proposal_id="proposal-validator-b"), context()
    )

    assert first.canonical_action_identity == second.canonical_action_identity


def test_live_and_replay_provenance_share_canonical_identity() -> None:
    live = validate(
        proposal(analysis_id="analysis-live"),
        replace(
            replace(context(), analysis_id="analysis-live"),
            provider_mode=ProviderMode.LIVE,
            replay_label=ProviderMode.LIVE,
        ),
    )
    replay = validate(
        proposal(proposal_id="proposal-replay", analysis_id="analysis-replay"),
        replace(
            replace(context(), analysis_id="analysis-replay"),
            provider_mode=ProviderMode.REPLAY,
            replay_label=ProviderMode.REPLAY,
        ),
    )

    assert live.status is ProposalValidationStatus.VALID
    assert replay.status is ProposalValidationStatus.VALID
    assert live.canonical_action_identity == replay.canonical_action_identity


def test_different_semantic_parameters_have_different_canonical_identity() -> None:
    first = validate(proposal(parameters={"reason": "review-a"}))
    second = validate(
        proposal(proposal_id="proposal-parameter-b", parameters={"reason": "review-b"})
    )

    assert first.status is ProposalValidationStatus.VALID
    assert second.status is ProposalValidationStatus.VALID
    assert first.canonical_action_identity != second.canonical_action_identity


def test_different_tenant_and_case_scopes_have_different_canonical_identity() -> None:
    base_resource = resource("order-t075", "orders", "timeline-order-t075")
    other_resource = replace(base_resource, tenant_id="tenant-other", case_id="case-other")
    first = canonical_action_identity(
        proposal(proposal_id="proposal-scope-a"),
        connector_id="action-connector-t075",
        resource=base_resource,
    )
    second = canonical_action_identity(
        proposal(
            proposal_id="proposal-scope-b",
            tenant_id="tenant-other",
            case_id="case-other",
        ),
        connector_id="action-connector-t075",
        resource=other_resource,
    )

    assert first != second


def test_canonical_identity_ignores_parameter_mapping_order() -> None:
    first = validate(
        proposal(
            proposal_id="proposal-order-a",
            parameters={"reason": "review", "review_reason": "bounded"},
        )
    )
    second = validate(
        proposal(
            proposal_id="proposal-order-b",
            parameters={"review_reason": "bounded", "reason": "review"},
        )
    )

    assert first.canonical_action_identity == second.canonical_action_identity


def test_canonical_identity_ignores_rationale() -> None:
    first = validate(proposal(proposal_id="proposal-rationale-a"))
    second = validate(
        proposal(
            proposal_id="proposal-rationale-b",
            rationale="A different non-semantic explanation.",
        )
    )

    assert first.canonical_action_identity == second.canonical_action_identity


def test_canonical_identity_ignores_provider_and_model_metadata() -> None:
    first = validate(
        proposal(proposal_id="proposal-metadata-a"),
        replace(context(), provider="provider-a", model="model-a"),
    )
    second = validate(
        proposal(proposal_id="proposal-metadata-b"),
        replace(context(), provider="provider-b", model="model-b"),
    )

    assert first.canonical_action_identity == second.canonical_action_identity


def test_different_target_has_different_canonical_identity() -> None:
    other_context = context(
        target="order-other-t075",
        timeline_event_id="timeline-order-other-t075",
    )

    first = validate(proposal(proposal_id="proposal-target-a"))
    second = validate(
        proposal(
            proposal_id="proposal-target-b",
            target_resource="order-other-t075",
            attribution_references=("timeline-order-other-t075",),
        ),
        other_context,
    )

    assert first.canonical_action_identity != second.canonical_action_identity


def test_different_action_type_has_different_canonical_identity() -> None:
    fulfillment = resource(
        "fulfillment-t075",
        "fulfillment",
        "timeline-fulfillment-t075",
    )
    state = context(
        target="fulfillment-t075",
        timeline_event_id="timeline-fulfillment-t075",
        target_resource=fulfillment,
    )

    first = validate(proposal(proposal_id="proposal-action-a"))
    second = validate(
        proposal(
            proposal_id="proposal-action-b",
            action_type=ActionType.HOLD_FULFILLMENT,
            target_resource="fulfillment-t075",
            attribution_references=("timeline-fulfillment-t075",),
        ),
        state,
    )

    assert first.canonical_action_identity != second.canonical_action_identity


def test_different_authoritative_refund_amount_has_different_identity() -> None:
    payment = resource(
        "payment-t075",
        "payments",
        "timeline-payment-t075",
        attributes={
            "state": "captured",
            "amount_minor": 10_000,
            "currency": "INR",
            "payment_source": "source-t075",
        },
    )
    state = context(
        target="payment-t075",
        timeline_event_id="timeline-payment-t075",
        target_resource=payment,
        exposure={"currency": "INR", "remaining_exposure_minor": 9_000},
    )

    first = validate(
        proposal(
            proposal_id="proposal-amount-a",
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-t075",
            attribution_references=("timeline-payment-t075",),
            requested_amount_minor=1_000,
            currency="INR",
        ),
        state,
    )
    second = validate(
        proposal(
            proposal_id="proposal-amount-b",
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-t075",
            attribution_references=("timeline-payment-t075",),
            requested_amount_minor=2_000,
            currency="INR",
        ),
        state,
    )

    assert first.status is ProposalValidationStatus.VALID
    assert second.status is ProposalValidationStatus.VALID
    assert first.canonical_action_identity != second.canonical_action_identity


def test_different_authoritative_refund_currency_has_different_identity() -> None:
    payment = resource(
        "payment-t075",
        "payments",
        "timeline-payment-t075",
        attributes={
            "state": "captured",
            "amount_minor": 10_000,
            "currency": "INR",
            "payment_source": "source-t075",
        },
    )
    first_state = context(
        target="payment-t075",
        timeline_event_id="timeline-payment-t075",
        target_resource=payment,
        exposure={"currency": "INR", "remaining_exposure_minor": 9_000},
    )
    usd_payment = replace(
        payment,
        attributes={**payment.attributes, "currency": "USD"},
    )
    second_state = context(
        target="payment-t075",
        timeline_event_id="timeline-payment-t075",
        target_resource=usd_payment,
        exposure={"currency": "USD", "remaining_exposure_minor": 9_000},
    )

    first = validate(
        proposal(
            proposal_id="proposal-currency-inr",
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-t075",
            attribution_references=("timeline-payment-t075",),
            requested_amount_minor=1_000,
            currency="INR",
        ),
        first_state,
    )
    second = validate(
        proposal(
            proposal_id="proposal-currency-usd",
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-t075",
            attribution_references=("timeline-payment-t075",),
            requested_amount_minor=1_000,
            currency="USD",
        ),
        second_state,
    )

    assert first.status is ProposalValidationStatus.VALID
    assert second.status is ProposalValidationStatus.VALID
    assert first.canonical_action_identity != second.canonical_action_identity


def test_different_authoritative_connector_has_different_identity() -> None:
    other_connector = "other-action-connector"
    other_manifest = action_manifest().model_copy(update={"connector_id": other_connector})
    other_resource = replace(
        resource("order-t075", "orders", "timeline-order-t075"), connector_id=other_connector
    )
    other_context = replace(
        context(target_resource=other_resource),
        connectors={other_connector: other_manifest},
        action_connector_ids={action.value: other_connector for action in ActionType},
    )

    first = validate(proposal(proposal_id="proposal-connector-a"))
    second = validate(
        proposal(proposal_id="proposal-connector-b"),
        other_context,
    )

    assert first.status is ProposalValidationStatus.VALID
    assert second.status is ProposalValidationStatus.VALID
    assert first.canonical_action_identity != second.canonical_action_identity


def test_existing_semantic_identity_under_another_key_remains_valid() -> None:
    first = validate(proposal(idempotency_key="key-a"))
    assert first.canonical_action_identity is not None
    state = context(
        existing_idempotency_keys={
            "legacy-key": first.canonical_action_identity,
        }
    )

    second = validate(proposal(idempotency_key="key-b"), state)

    assert second.status is ProposalValidationStatus.VALID
    assert second.canonical_action_identity == first.canonical_action_identity


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
