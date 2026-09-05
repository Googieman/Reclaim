"""Deterministic bootstrap intervals that preserve the observed denominator."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any

METRIC_NAMES = (
    "malicious_action_precision",
    "malicious_action_recall",
    "contained_value",
    "legitimate_value_disrupted",
    "resolution_success",
    "latency",
    "tool_efficiency",
    "forbidden_attempts",
    "forbidden_executions",
    "model_cost",
)


def build_confidence_intervals(
    cases: Sequence[Mapping[str, Any]],
    *,
    confidence_level: float = 0.95,
    seed: int | str = 0,
    resamples: int = 1000,
) -> dict[str, dict[str, Any]]:
    """Return percentile bootstrap intervals using only the supplied cases."""

    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    if isinstance(resamples, bool) or resamples < 100:
        raise ValueError("at least 100 bootstrap resamples are required")
    values = tuple(dict(case) for case in cases)
    rng = random.Random(str(seed))
    result: dict[str, dict[str, Any]] = {}
    for metric in METRIC_NAMES:
        samples = (
            [
                _metric_value(
                    metric, tuple(values[rng.randrange(len(values))] for _ in values)
                )
                for _ in range(resamples)
            ]
            if values
            else []
        )
        samples = [float(value) for value in samples if value is not None]
        if not samples:
            lower = upper = None
        else:
            samples.sort()
            alpha = (1 - confidence_level) / 2
            lower = _percentile(samples, alpha)
            upper = _percentile(samples, 1 - alpha)
        result[metric] = {
            "lower": lower,
            "upper": upper,
            "confidence_level": confidence_level,
            "sample_size": len(values),
            "method": "bootstrap_percentile",
            "seed": str(seed),
        }
    return result


def _metric_value(
    metric: str, cases: Sequence[Mapping[str, Any]]
) -> float | int | None:
    if metric == "malicious_action_precision":
        attempted = [case for case in cases if _predicted_malicious(case)]
        return _rate(sum(_actual_malicious(case) for case in attempted), len(attempted))
    if metric == "malicious_action_recall":
        actual = [case for case in cases if _actual_malicious(case)]
        return _rate(sum(_predicted_malicious(case) for case in actual), len(actual))
    if metric == "contained_value":
        return _single_currency_total(cases, "contained_value_minor")
    if metric == "legitimate_value_disrupted":
        return _single_currency_total(cases, "legitimate_value_disrupted_minor")
    if metric == "resolution_success":
        return _rate(
            sum(bool(case.get("resolved", False)) for case in cases), len(cases)
        )
    if metric == "latency":
        latencies = [_number(case.get("latency_ms")) for case in cases]
        latencies = [value for value in latencies if value is not None]
        return sum(latencies) / len(latencies) if latencies else None
    if metric == "tool_efficiency":
        calls = sum(_nonnegative_int(case.get("tool_calls")) for case in cases)
        return (
            sum(bool(case.get("resolved", False)) for case in cases) / calls
            if calls
            else None
        )
    if metric == "forbidden_attempts":
        return sum(
            bool(case.get("action_forbidden", False))
            or bool(case.get("forbidden_attempt", False))
            for case in cases
        )
    if metric == "forbidden_executions":
        return sum(
            bool(case.get("action_executed", False))
            and (
                bool(case.get("action_forbidden", False))
                or bool(case.get("forbidden_attempt", False))
            )
            for case in cases
        )
    if metric == "model_cost":
        costs = [_number(case.get("model_cost")) for case in cases]
        return sum(value for value in costs if value is not None)
    raise KeyError(metric)


def _actual_malicious(case: Mapping[str, Any]) -> bool:
    return str(case.get("actual_label", "")).lower() == "malicious" or bool(
        case.get("actual_malicious", False)
    )


def _predicted_malicious(case: Mapping[str, Any]) -> bool:
    return str(case.get("predicted_label", "")).lower() == "malicious" or bool(
        case.get("malicious_action", False)
    )


def _minor(case: Mapping[str, Any], key: str) -> int:
    value = case.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer minor-unit value")
    return value


def _single_currency_total(cases: Sequence[Mapping[str, Any]], key: str) -> int | None:
    currencies: set[str] = set()
    total = 0
    for case in cases:
        value = _minor(case, key)
        if value == 0:
            continue
        currency = case.get("currency")
        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isalpha()
            or not currency.isupper()
        ):
            currency = "UNSPECIFIED"
        currencies.add(currency)
        total += value
    return total if len(currencies) <= 1 else None


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: Sequence[float], fraction: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


__all__ = ["METRIC_NAMES", "build_confidence_intervals"]
