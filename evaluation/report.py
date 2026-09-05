"""Stable evaluation report assembly with provenance and statistical limits."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .confidence_intervals import build_confidence_intervals
from .drift import detect_drift
from .metrics import calculate_metrics

REPORT_VERSION = "evaluation-report-v1.0.0"
REQUIRED_PROVENANCE_FIELDS = (
    "dataset_version",
    "manifest_version",
    "manifest_checksum",
    "split",
    "model_profile",
    "evaluator_version",
    "environment_version",
)


def build_report(
    cases: Sequence[Mapping[str, Any]],
    *,
    provenance: Mapping[str, Any],
    confidence_level: float = 0.95,
    seed: int | str = 0,
    report_id: str | None = None,
    drift_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = calculate_metrics(cases, provenance=provenance)
    intervals = build_confidence_intervals(
        cases, confidence_level=confidence_level, seed=seed
    )
    drift = (
        detect_drift(drift_baseline, {"class_balance": metrics["class_balance"]})
        if drift_baseline is not None
        else None
    )
    identifier = (
        report_id
        or "metrics:"
        + hashlib.sha256(
            json.dumps(
                {
                    "version": REPORT_VERSION,
                    "provenance": dict(provenance),
                    "sample_size": len(cases),
                    "seed": str(seed),
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()[:32]
    )
    return {
        "report_id": identifier,
        "report_version": REPORT_VERSION,
        **metrics,
        "confidence_intervals": intervals,
        "confidence_interval_method": "bootstrap_percentile",
        "confidence_level": confidence_level,
        "bootstrap_seed": str(seed),
        "actual_sample_size": len(cases),
        "provenance_complete": all(
            isinstance(provenance.get(field), str) and bool(provenance[field].strip())
            for field in REQUIRED_PROVENANCE_FIELDS
        ),
        "confidence_interval_provenance": {
            "report_version": REPORT_VERSION,
            "method": "bootstrap_percentile",
            "confidence_level": confidence_level,
            "seed": str(seed),
            "sample_size": len(cases),
            "dataset_version": provenance.get("dataset_version"),
            "manifest_version": provenance.get("manifest_version"),
            "manifest_checksum": provenance.get("manifest_checksum"),
        },
        "drift": drift,
        "synthetic_is_not_production": metrics["qualification"] != "live-qualified",
    }


__all__ = ["REPORT_VERSION", "REQUIRED_PROVENANCE_FIELDS", "build_report"]
