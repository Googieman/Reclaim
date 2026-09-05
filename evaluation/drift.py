"""Small, deterministic distribution-drift gate for evaluation reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DRIFT_VERSION = "evaluation-drift-v1.0.0"


def detect_drift(
    baseline: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    *,
    max_absolute_rate_delta: float = 0.10,
) -> dict[str, Any]:
    """Compare class distributions and fail closed when either side is absent."""

    if not 0 <= max_absolute_rate_delta <= 1:
        raise ValueError("max_absolute_rate_delta must be between zero and one")
    if not isinstance(baseline, Mapping) or not isinstance(current, Mapping):
        return {
            "status": "unavailable",
            "drift_detected": True,
            "version": DRIFT_VERSION,
            "limitations": ["baseline and current distributions are required"],
        }
    baseline_counts = _counts(baseline.get("class_balance"), "baseline")
    current_counts = _counts(current.get("class_balance"), "current")
    if baseline_counts is None or current_counts is None:
        return {
            "status": "unavailable",
            "drift_detected": True,
            "version": DRIFT_VERSION,
            "limitations": ["class distributions must contain non-negative counts"],
        }
    baseline_total = sum(baseline_counts.values())
    current_total = sum(current_counts.values())
    if not baseline_total or not current_total:
        return {
            "status": "unavailable",
            "drift_detected": True,
            "version": DRIFT_VERSION,
            "limitations": ["non-empty baseline and current distributions are required"],
        }
    deltas = {
        key: round(
            current_counts.get(key, 0) / current_total
            - baseline_counts.get(key, 0) / baseline_total,
            6,
        )
        for key in sorted(set(baseline_counts) | set(current_counts))
    }
    drifted = {key: value for key, value in deltas.items() if abs(value) > max_absolute_rate_delta}
    return {
        "status": "fail" if drifted else "pass",
        "drift_detected": bool(drifted),
        "version": DRIFT_VERSION,
        "threshold": max_absolute_rate_delta,
        "baseline_sample_size": baseline_total,
        "current_sample_size": current_total,
        "rate_deltas": deltas,
        "drifted_dimensions": drifted,
        "limitations": [],
    }


check_drift = detect_drift


def _counts(value: Any, name: str) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    counts: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            return None
        counts[str(key)] = item
    return counts


__all__ = ["DRIFT_VERSION", "check_drift", "detect_drift"]
