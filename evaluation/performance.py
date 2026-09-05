"""Measured performance capture; targets are provisional design comparisons only."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

PERFORMANCE_VERSION = "performance-baseline-v1.0.0"


def measure_performance(
    operation: Callable[[], Any],
    *,
    iterations: int = 1,
    warmup_iterations: int = 0,
    recovery_operation: Callable[[], Any] | None = None,
    environment: Mapping[str, Any] | None = None,
    qualification: str = "local-replay-harness",
) -> dict[str, Any]:
    """Measure only the callable supplied by the caller and report all failures."""

    if not callable(operation):
        raise TypeError("performance operation must be callable")
    if isinstance(iterations, bool) or iterations < 1:
        raise ValueError("iterations must be positive")
    if isinstance(warmup_iterations, bool) or warmup_iterations < 0:
        raise ValueError("warmup_iterations cannot be negative")
    for _ in range(warmup_iterations):
        operation()
    samples: list[float] = []
    failures = 0
    total_started = time.perf_counter()
    for _ in range(iterations):
        started = time.perf_counter()
        try:
            operation()
        except Exception:
            failures += 1
        else:
            samples.append((time.perf_counter() - started) * 1000)
    total_elapsed = time.perf_counter() - total_started
    recovery_ms: float | None = None
    recovery_failure = False
    if recovery_operation is not None:
        started = time.perf_counter()
        try:
            recovery_operation()
        except Exception:
            recovery_failure = True
        else:
            recovery_ms = (time.perf_counter() - started) * 1000
    return {
        "measurement_version": PERFORMANCE_VERSION,
        "qualification": qualification,
        "environment": dict(environment or {}),
        "sample_size": iterations,
        "successful_samples": len(samples),
        "warmup_iterations": warmup_iterations,
        "p50_latency_ms": _percentile(sorted(samples), 0.50),
        "p95_latency_ms": _percentile(sorted(samples), 0.95),
        "throughput_per_second": len(samples) / total_elapsed
        if total_elapsed
        else None,
        "recovery_time_ms": recovery_ms,
        "failure_count": failures,
        "failure_rate": failures / iterations,
        "recovery_failure": recovery_failure,
        "timing_scope": "supplied callable only",
        "measured": True,
    }


def compare_provisional_targets(
    measurement: Mapping[str, Any],
    *,
    intake_p95_target_seconds: float = 2.0,
    replay_p95_target_seconds: float = 300.0,
) -> dict[str, Any]:
    """Compare measured values with design targets without calling them SLOs."""

    p95_ms = measurement.get("p95_latency_ms")
    p95_seconds = None if p95_ms is None else float(p95_ms) / 1000
    return {
        "target_type": "provisional design target",
        "release_slo_claim": False,
        "intake_p95": {
            "target_seconds": intake_p95_target_seconds,
            "measured_seconds": p95_seconds,
            "status": _status(p95_seconds, intake_p95_target_seconds),
        },
        "replay_p95": {
            "target_seconds": replay_p95_target_seconds,
            "measured_seconds": p95_seconds,
            "status": _status(p95_seconds, replay_p95_target_seconds),
        },
    }


capture_baseline = measure_performance
run_performance_baseline = measure_performance


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _status(value: float | None, target: float) -> str:
    if value is None:
        return "not_measured"
    return (
        "within_provisional_target" if value <= target else "above_provisional_target"
    )


__all__ = [
    "PERFORMANCE_VERSION",
    "capture_baseline",
    "compare_provisional_targets",
    "measure_performance",
    "run_performance_baseline",
]
