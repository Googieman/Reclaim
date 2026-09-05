"""T108 evaluation metric and confidence-interval boundaries."""

from __future__ import annotations

import importlib
from typing import Any


def _require_symbol(module_name: str, symbol_name: str, *, task: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing_name = exc.name or "unknown module"
        if missing_name == module_name or module_name.startswith(f"{missing_name}."):
            raise AssertionError(
                f"{task} production seam is not implemented: {module_name}.{symbol_name}"
            ) from exc
        raise
    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        raise AssertionError(
            f"{task} production seam is missing: {module_name}.{symbol_name}"
        ) from exc


CASES = (
    {
        "actual_label": "malicious",
        "predicted_label": "malicious",
        "action_attempted": True,
        "action_forbidden": False,
        "action_executed": True,
        "contained_value_minor": 10_000,
        "legitimate_value_disrupted_minor": 0,
        "resolved": True,
        "latency_ms": 120,
        "tool_calls": 2,
        "model_cost": 0.03,
    },
    {
        "actual_label": "legitimate",
        "predicted_label": "legitimate",
        "action_attempted": False,
        "action_forbidden": False,
        "action_executed": False,
        "contained_value_minor": 0,
        "legitimate_value_disrupted_minor": 0,
        "resolved": True,
        "latency_ms": 80,
        "tool_calls": 1,
        "model_cost": 0.02,
    },
    {
        "actual_label": "uncertain",
        "predicted_label": "uncertain",
        "action_attempted": True,
        "action_forbidden": True,
        "action_executed": False,
        "contained_value_minor": 0,
        "legitimate_value_disrupted_minor": 0,
        "resolved": False,
        "latency_ms": 160,
        "tool_calls": 3,
        "model_cost": 0.04,
    },
)

PROVENANCE = {
    "dataset_version": "development-v1.0.0",
    "split": "development",
    "policy_version_id": "policy-v1.0.0",
    "model_version": "replay-fixture/provider-v1.0.0",
    "environment": "deterministic-test",
}


def test_metrics_report_required_safety_measures_actual_count_and_provenance() -> None:
    calculate_metrics = _require_symbol(
        "evaluation.metrics", "calculate_metrics", task="T117"
    )
    build_confidence_intervals = _require_symbol(
        "evaluation.confidence_intervals",
        "build_confidence_intervals",
        task="T117",
    )

    report = calculate_metrics(CASES, provenance=PROVENANCE)
    intervals = build_confidence_intervals(CASES, confidence_level=0.95, seed=108)

    required_metrics = {
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
    }
    assert report["sample_size"] == len(CASES)
    assert set(report["metrics"]) >= required_metrics
    assert report["provenance"] == PROVENANCE
    assert report["limitations"]
    assert set(intervals) >= required_metrics
    assert all(
        set(value) >= {"lower", "upper", "confidence_level"}
        for value in intervals.values()
    )
