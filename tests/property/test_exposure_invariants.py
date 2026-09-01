"""Test-first financial exposure properties for the future T068 calculator."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from hypothesis import given, strategies as st
from hypothesis import settings

from us2_test_seams import require_symbol


TENANT_ID = "tenant-us2-exposure"
CASE_ID = "case-us2-exposure"
CALCULATION_VERSION = "exposure-v1.0.0"


def payment(
    *,
    payment_id: str,
    amount_minor: int,
    label: str = "malicious",
    reimbursed_minor: int = 0,
    contained_minor: int = 0,
    payment_state: str = "captured",
    currency: str | None = "INR",
    payment_source: str | None = "source-card-1",
    linked_case_id: str | None = CASE_ID,
    legitimate_value_disrupted_minor: int = 0,
) -> dict[str, Any]:
    return {
        "payment_id": payment_id,
        "timeline_event_id": f"timeline-{payment_id}",
        "evidence_references": (f"evidence-{payment_id}",),
        "tenant_id": TENANT_ID,
        "case_id": linked_case_id,
        "amount_minor": amount_minor,
        "currency": currency,
        "payment_state": payment_state,
        "payment_source": payment_source,
        "reimbursed_minor": reimbursed_minor,
        "contained_minor": contained_minor,
        "attribution_label": label,
        "legitimate_value_disrupted_minor": legitimate_value_disrupted_minor,
    }


def calculate(payments: tuple[dict[str, Any], ...]) -> Any:
    calculator = require_symbol(
        "finance.exposure",
        "calculate_exposure",
        task="T061/T068",
    )
    return calculator(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        payments=payments,
        calculation_version=CALCULATION_VERSION,
    )


def result_field(result: Any, name: str) -> Any:
    if isinstance(result, Mapping):
        return result[name]
    return getattr(result, name)


def assert_exposure(
    result: Any,
    *,
    currency: str,
    gross: int,
    recoverable: int,
    contained: int,
    legitimate_disrupted: int,
    irreversible_loss: int,
    remaining: int,
) -> None:
    assert result_field(result, "currency") == currency
    assert result_field(result, "gross_exposure_minor") == gross
    assert result_field(result, "recoverable_value_minor") == recoverable
    assert result_field(result, "contained_value_minor") == contained
    assert (
        result_field(result, "legitimate_value_disrupted_minor") == legitimate_disrupted
    )
    assert result_field(result, "irreversible_loss_minor") == irreversible_loss
    assert result_field(result, "remaining_exposure_minor") == remaining
    for field in (
        "gross_exposure_minor",
        "recoverable_value_minor",
        "contained_value_minor",
        "legitimate_value_disrupted_minor",
        "irreversible_loss_minor",
        "remaining_exposure_minor",
    ):
        value = result_field(result, field)
        assert isinstance(value, int)
        assert not isinstance(value, bool)
        assert value >= 0


def test_partial_recovery_uses_exact_minor_units_and_excludes_uncertain_activity() -> (
    None
):
    result = calculate(
        (
            payment(
                payment_id="payment-malicious-partial",
                amount_minor=12_345,
                reimbursed_minor=2_345,
                contained_minor=7_000,
            ),
            payment(
                payment_id="payment-legitimate-disrupted",
                amount_minor=9_000,
                label="legitimate",
                legitimate_value_disrupted_minor=1_200,
            ),
            payment(
                payment_id="payment-uncertain",
                amount_minor=6_400,
                label="uncertain",
            ),
        )
    )

    assert_exposure(
        result,
        currency="INR",
        gross=12_345,
        recoverable=10_000,
        contained=7_000,
        legitimate_disrupted=1_200,
        irreversible_loss=2_345,
        remaining=3_000,
    )


@st.composite
def recoverable_payment_values(draw: st.DrawFn) -> tuple[int, int, int]:
    amount = draw(st.integers(min_value=0, max_value=10**12))
    max_reimbursed = amount if amount == 0 else amount - 1
    reimbursed = draw(st.integers(min_value=0, max_value=max_reimbursed))
    contained = draw(st.integers(min_value=0, max_value=amount - reimbursed))
    return amount, reimbursed, contained


@settings(max_examples=25, deadline=None)
@given(values=recoverable_payment_values())
def test_random_minor_unit_values_preserve_exposure_bounds(
    values: tuple[int, int, int],
) -> None:
    amount, reimbursed, contained = values
    result = calculate(
        (
            payment(
                payment_id="payment-property",
                amount_minor=amount,
                reimbursed_minor=reimbursed,
                contained_minor=contained,
            ),
        )
    )

    assert_exposure(
        result,
        currency="INR",
        gross=amount,
        recoverable=amount - reimbursed,
        contained=contained,
        legitimate_disrupted=0,
        irreversible_loss=reimbursed,
        remaining=amount - reimbursed - contained,
    )
    assert 0 <= result_field(result, "recoverable_value_minor") <= amount
    assert 0 <= result_field(result, "contained_value_minor") <= amount
    assert result_field(result, "contained_value_minor") <= result_field(
        result, "recoverable_value_minor"
    )
    assert result_field(result, "remaining_exposure_minor") <= amount


def test_duplicate_timeline_payment_records_do_not_double_count_exposure() -> None:
    item = payment(
        payment_id="payment-deduplicated",
        amount_minor=8_765,
        reimbursed_minor=765,
        contained_minor=2_000,
    )

    single = calculate((item,))
    duplicate = calculate((item, dict(item)))

    assert duplicate == single


def test_payment_delivery_order_does_not_change_exposure() -> None:
    payments = (
        payment(payment_id="payment-order-1", amount_minor=1_100),
        payment(payment_id="payment-order-2", amount_minor=2_200, contained_minor=500),
    )

    assert calculate(payments) == calculate(tuple(reversed(payments)))


@pytest.mark.parametrize(
    "invalid_payment",
    (
        payment(
            payment_id="payment-uncaptured",
            amount_minor=100,
            payment_state="authorized",
        ),
        payment(
            payment_id="payment-unlinked",
            amount_minor=100,
            linked_case_id=None,
        ),
        payment(
            payment_id="payment-fully-reimbursed",
            amount_minor=100,
            reimbursed_minor=100,
        ),
        payment(
            payment_id="payment-no-source",
            amount_minor=100,
            payment_source=None,
        ),
        payment(
            payment_id="payment-unknown-source",
            amount_minor=100,
            payment_source="unknown_source",
        ),
        payment(
            payment_id="payment-no-currency",
            amount_minor=100,
            currency=None,
        ),
    ),
)
def test_refund_inputs_without_captured_bounded_source_are_rejected(
    invalid_payment: dict[str, Any],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        calculate((invalid_payment,))


@pytest.mark.parametrize("invalid_payments", ("cross_currency", "cross_tenant"))
def test_cross_currency_and_cross_tenant_inputs_are_rejected(
    invalid_payments: str,
) -> None:
    first = payment(payment_id=f"payment-{invalid_payments}-1", amount_minor=100)
    second = payment(
        payment_id=f"payment-{invalid_payments}-2",
        amount_minor=200,
        currency="USD" if invalid_payments == "cross_currency" else "INR",
    )
    if invalid_payments == "cross_tenant":
        second["tenant_id"] = "tenant-other"

    with pytest.raises((TypeError, ValueError)):
        calculate((first, second))


def test_zero_and_large_minor_values_remain_nonnegative_and_currency_explicit() -> None:
    result = calculate(
        (
            payment(payment_id="payment-zero", amount_minor=0),
            payment(payment_id="payment-large", amount_minor=10**15),
        )
    )

    assert_exposure(
        result,
        currency="INR",
        gross=10**15,
        recoverable=10**15,
        contained=0,
        legitimate_disrupted=0,
        irreversible_loss=0,
        remaining=10**15,
    )
