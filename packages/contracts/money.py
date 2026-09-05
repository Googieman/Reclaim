"""Deterministic minor-unit money parsing for incident intake.

The intake value is unverified user input.  This module only normalizes a
decimal display value into integer minor units; it never establishes payment
authority or eligibility for a refund.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ISO 4217 minor-unit metadata for currencies supported by the intake form.
# Unknown currencies fail closed instead of guessing their precision.
CURRENCY_MINOR_UNITS: dict[str, int] = {
    "BHD": 3,
    "CLP": 0,
    "CNY": 2,
    "EUR": 2,
    "GBP": 2,
    "INR": 2,
    "JPY": 0,
    "KWD": 3,
    "KRW": 0,
    "RUB": 2,
    "SGD": 2,
    "USD": 2,
    "VND": 0,
}


class MoneyParseError(ValueError):
    """Raised when a decimal amount cannot be represented safely."""


def currency_minor_units(currency: str) -> int:
    code = currency.strip().upper()
    try:
        return CURRENCY_MINOR_UNITS[code]
    except KeyError as exc:
        raise MoneyParseError(f"unsupported ISO currency: {code or '<blank>'}") from exc


def decimal_to_minor_units(value: str | Decimal, currency: str) -> int:
    """Convert a base-10 decimal string using integer arithmetic semantics.

    Values with more fractional precision than the ISO currency supports are
    rejected rather than silently rounded.  Scientific notation is accepted by
    ``Decimal`` but floating-point inputs are intentionally not.
    """

    if isinstance(value, float):
        raise MoneyParseError("floating-point amounts are not accepted")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MoneyParseError("amount must be a valid decimal string") from exc
    if not amount.is_finite() or amount < 0:
        raise MoneyParseError("amount must be finite and non-negative")
    units = currency_minor_units(currency)
    scale = Decimal(10) ** units
    minor = amount * scale
    if minor != minor.to_integral_value(rounding=ROUND_HALF_UP):
        raise MoneyParseError(f"amount has more than {units} minor-unit decimals")
    return int(minor)


__all__ = [
    "CURRENCY_MINOR_UNITS",
    "MoneyParseError",
    "currency_minor_units",
    "decimal_to_minor_units",
]
