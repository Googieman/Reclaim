"""Contract coverage for bounded typed defensive proposals."""

import pytest
from pydantic import ValidationError

from packages.contracts.analysis_policy import ActionType, TypedActionProposal


def proposal(**overrides: object) -> TypedActionProposal:
    values: dict[str, object] = {
        "tenant_id": "tenant-us2-proposals",
        "correlation_id": "corr-us2-proposals",
        "proposal_id": "proposal-us2-typed-1",
        "case_id": "case-us2-proposals",
        "action_type": ActionType.HOLD_FULFILLMENT,
        "target_resource": "fulfillment-1",
        "parameters": {"hold_reason": "review_required"},
        "rationale": "Hold fulfillment while the case is reviewed.",
        "evidence_references": ("evidence-order-1",),
        "attribution_references": ("timeline-event-1",),
        "idempotency_key": "proposal-us2-typed-1-key",
        "analysis_id": "analysis-us2-proposals",
    }
    values.update(overrides)
    return TypedActionProposal(**values)


def test_typed_proposal_retains_scope_provenance_amount_and_idempotency() -> None:
    result = proposal(
        action_type=ActionType.REFUND_PAYMENT,
        target_resource="payment-captured-1",
        requested_amount_minor=1_250,
        currency="INR",
    )

    assert result.tenant_id == "tenant-us2-proposals"
    assert result.case_id == "case-us2-proposals"
    assert result.action_type is ActionType.REFUND_PAYMENT
    assert result.evidence_references == ("evidence-order-1",)
    assert result.attribution_references == ("timeline-event-1",)
    assert result.requested_amount_minor == 1_250
    assert result.currency == "INR"
    assert result.idempotency_key == "proposal-us2-typed-1-key"
    assert TypedActionProposal.model_validate(result.model_dump()) == result


@pytest.mark.parametrize(
    "overrides",
    (
        {"action_type": "execute_payment"},
        {"requested_amount_minor": -1, "currency": "INR"},
        {"action_type": ActionType.REFUND_PAYMENT},
        {"requested_amount_minor": 100},
        {"shell_command": "curl attacker.example"},
    ),
)
def test_typed_proposal_rejects_malformed_or_uncontracted_output(
    overrides: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError, ValidationError)):
        proposal(**overrides)


def test_typed_proposal_does_not_expose_free_form_execution_instructions() -> None:
    result = proposal()

    assert "instructions" not in result.model_dump()
    assert "command" not in result.model_dump()
    assert isinstance(result.parameters, dict)
