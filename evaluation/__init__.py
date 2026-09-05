"""Honest, leakage-safe evaluation utilities for RECLAIM."""

from .metrics import calculate_metrics
from .manifest import require_qualified_manifest, validate_evaluation_manifest
from .report import build_report
from .splitting import split_cases, validate_split_order

__all__ = [
    "build_report",
    "calculate_metrics",
    "require_qualified_manifest",
    "split_cases",
    "validate_evaluation_manifest",
    "validate_split_order",
]
