"""T083 deterministic refund and financial-safety tests."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from finance.exposure import ExposureValidationError, calculate_exposure
from packages.contracts.analysis_policy import ActionType, TypedActionProposal
from app.control_plane.tenant_config import TenantConfiguration
from us3_test_seams import require_symbol


TENANT_ID = "tenant-us3-finance"
CASE_ID = "case-us3-finance-001"


def _payment(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "case_id": CASE_ID,
        "payment_id": "payment-us3-001",
        "timeline_event_id": "timeline-payment-us3-001",
        "state": "captured",
        "amount_minor": 10_000,
        "currency": "INR",
        "payment_source": "source-card-us3-001",
        "reimbursed_minor": 2_000,
        "contained_minor": 3_000,
        "label": "malicious",
    }
    values.update(overrides)
    return values


def test_captured_payment_with_positive_unreimbursed_amount_is_bounded() -> None:
    exposure = calculate_exposure(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        payments=[_payment()],
        calculation_version="exposure-us3-v1.0.0",
    )

    assert exposure.gross_exposure_minor == 10_000
    assert exposure.recoverable_value_minor == 8_000
    assert exposure.contained_value_minor == 3_000
    assert exposure.irreversible_loss_minor == 2_000
    assert exposure.remaining_exposure_minor == 5_000
    assert exposure.currency == "INR"


@pytest.mark.parametrize("state", ("authorized", "created", "failed", "uncaptured"))
def test_uncaptured_payment_cannot_enter_refund_authority(state: str) -> None:
    with pytest.raises(ExposureValidationError, match="captured"):
        calculate_exposure(
            tenant_id=TENANT_ID,
            case_id=CASE_ID,
            payments=[_payment(state=state)],
            calculation_version="exposure-us3-v1.0.0",
        )


def test_fully_reimbursed_and_over_refunded_values_fail_closed() -> None:
    for payment in (
        _payment(reimbursed_minor=10_000),
        _payment(reimbursed_minor=10_001),
        _payment(contained_minor=8_001),
    ):
        with pytest.raises(ExposureValidationError):
            calculate_exposure(
                tenant_id=TENANT_ID,
                case_id=CASE_ID,
                payments=[payment],
                calculation_version="exposure-us3-v1.0.0",
            )


def test_missing_or_unknown_original_payment_source_fails_closed() -> None:
    for source in (None, "unknown_source", "unavailable"):
        with pytest.raises(ExposureValidationError):
            calculate_exposure(
                tenant_id=TENANT_ID,
                case_id=CASE_ID,
                payments=[_payment(payment_source=source)],
                calculation_version="exposure-us3-v1.0.0",
            )


def test_missing_or_cross_currency_payment_fails_closed() -> None:
    with pytest.raises(ExposureValidationError, match="currency"):
        calculate_exposure(
            tenant_id=TENANT_ID,
            case_id=CASE_ID,
            payments=[_payment(currency=None)],
            calculation_version="exposure-us3-v1.0.0",
        )

    with pytest.raises(ExposureValidationError, match="multiple currencies"):
        calculate_exposure(
            tenant_id=TENANT_ID,
            case_id=CASE_ID,
            payments=[
                _payment(),
                _payment(payment_id="payment-us3-002", currency="USD"),
            ],
            calculation_version="exposure-us3-v1.0.0",
        )


def test_payment_and_case_tenant_binding_is_authoritative() -> None:
    with pytest.raises(ExposureValidationError, match="outside"):
        calculate_exposure(
            tenant_id=TENANT_ID,
            case_id=CASE_ID,
            payments=[_payment(tenant_id="tenant-other")],
            calculation_version="exposure-us3-v1.0.0",
        )
    with pytest.raises(ExposureValidationError, match="outside"):
        calculate_exposure(
            tenant_id=TENANT_ID,
            case_id=CASE_ID,
            payments=[_payment(case_id="case-other")],
            calculation_version="exposure-us3-v1.0.0",
        )


def test_refund_proposal_requires_explicit_minor_amount_and_currency() -> None:
    with pytest.raises(ValueError, match="explicit currency"):
        TypedActionProposal(
            tenant_id=TENANT_ID,
            correlation_id="corr-us3-finance-001",
            proposal_id="proposal-us3-refund-001",
            case_id=CASE_ID,
            action_type=ActionType.REFUND_PAYMENT,
            target_resource="payment-us3-001",
            rationale="refund bounded captured payment",
            requested_amount_minor=5_000,
            idempotency_key="occurrence-us3-refund-001",
            analysis_id="analysis-us3-001",
        )


def test_live_financial_execution_is_disabled_by_default_in_both_boundaries() -> None:
    settings = Settings(_env_file=None)
    tenant_config = TenantConfiguration(
        tenant_id=TENANT_ID,
        connector_ids=frozenset({"razorpay-test"}),
        policy_version_id="policy-us3-v1.0.0",
    )

    assert settings.live_financial_actions_enabled is False
    assert tenant_config.live_financial_actions_enabled is False


@pytest.mark.xfail(
    strict=True,
    reason="Expected-red owner T094: Razorpay refund authority and adapter are not implemented",
)
def test_refund_authority_rejects_untrusted_destination_and_model_metadata() -> None:
    validate_refund = require_symbol(
        "connectors.razorpay.actions",
        "validate_refund_action",
        task="T083 -> T094",
    )
    action = {
        "tenant_id": TENANT_ID,
        "case_id": CASE_ID,
        "payment_id": "payment-us3-001",
        "captured": True,
        "amount_minor": 10_000,
        "reimbursed_minor": 2_000,
        "requested_amount_minor": 8_000,
        "currency": "INR",
        "original_payment_source": "source-card-us3-001",
        "refund_destination": "attacker-controlled-account",
        "model_metadata": {"amount_minor": 99_999, "currency": "USD"},
        "policy_version_id": "policy-us3-v1.0.0",
        "proposal_id": "proposal-us3-refund-001",
    }
    result = validate_refund(action)
    assert result.allowed is False
    assert result.reason
