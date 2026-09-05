"""Bounded operational metrics with correlation-safe event records.

Metric labels deliberately exclude tenant, case, and correlation identifiers.  Those
identifiers belong in traces and structured logs, where they can be sampled and
redacted, not in Prometheus labels with unbounded cardinality.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

METRIC_NAMES = {
    "backup_verification": "reclaim_backup_verification_total",
    "backup_last_success_timestamp": "reclaim_backup_last_success_timestamp_seconds",
    "orchestration_stage_duration_seconds": "reclaim_orchestration_stage_duration_seconds",
    "orchestration_stalled": "reclaim_orchestration_stalled_total",
    "recovery_events": "reclaim_recovery_events_total",
    "action_outcome": "reclaim_action_outcome_total",
    "postgres_health": "reclaim_postgres_health",
}
_LABELS = {
    "backup_verification": {"status"},
    "orchestration_stage_duration_seconds": {"stage"},
    "orchestration_stalled": {"stage"},
    "recovery_events": {"service", "outcome"},
    "action_outcome": {"outcome"},
    "postgres_health": {"status"},
}
_CORRELATION_KEYS = frozenset({"correlation_id", "case_id", "workflow_id", "action_id"})
_PROMETHEUS = CollectorRegistry()
_PROM_COUNTERS = {
    "backup_verification": Counter(
        "reclaim_backup_verification_total",
        "Backup checksum and restore verification outcomes.",
        ["status"],
        registry=_PROMETHEUS,
    ),
    "orchestration_stalled": Counter(
        "reclaim_orchestration_stalled_total",
        "Orchestration stalls requiring recovery.",
        ["stage"],
        registry=_PROMETHEUS,
    ),
    "recovery_events": Counter(
        "reclaim_recovery_events_total",
        "Service recovery outcomes.",
        ["service", "outcome"],
        registry=_PROMETHEUS,
    ),
    "action_outcome": Counter(
        "reclaim_action_outcome_total",
        "Typed Action Gateway outcomes.",
        ["outcome"],
        registry=_PROMETHEUS,
    ),
}
_PROM_STAGE_DURATION = Histogram(
    "reclaim_orchestration_stage_duration_seconds",
    "Orchestration stage duration.",
    ["stage"],
    registry=_PROMETHEUS,
)
_PROM_BACKUP_LAST_SUCCESS = Gauge(
    "reclaim_backup_last_success_timestamp_seconds",
    "Unix timestamp of the last verified backup.",
    registry=_PROMETHEUS,
)
_PROM_POSTGRES_HEALTH = Gauge(
    "reclaim_postgres_health",
    "Authoritative PostgreSQL readiness (one when ready).",
    ["status"],
    registry=_PROMETHEUS,
)


class MetricRegistry:
    """Small in-memory registry used by tests and non-Prometheus adapters."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def inc(
        self,
        metric: str,
        *,
        labels: Mapping[str, str] | None = None,
        context: Mapping[str, str] | None = None,
        value: float = 1.0,
    ) -> dict[str, Any]:
        return self._record(metric, value, labels=labels, context=context)

    def observe(
        self,
        metric: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
        context: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._record(metric, value, labels=labels, context=context)

    def records(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self._records]

    def _record(
        self,
        metric: str,
        value: float,
        *,
        labels: Mapping[str, str] | None,
        context: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        if metric not in METRIC_NAMES:
            raise ValueError(f"unknown operational metric: {metric}")
        record = {
            "metric": METRIC_NAMES[metric],
            "value": float(value),
            "labels": {
                key: str(item)
                for key, item in (labels or {}).items()
                if key in _LABELS.get(metric, set())
            },
            "correlation": {
                key: str(item)
                for key, item in (context or {}).items()
                if key in _CORRELATION_KEYS and str(item).strip()
            },
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        self._records.append(record)
        return dict(record)


def set_postgres_health(ready: bool) -> None:
    """Set the readiness gauge without adding tenant or case labels."""

    _PROM_POSTGRES_HEALTH.labels(status="ready").set(1 if ready else 0)
    _PROM_POSTGRES_HEALTH.labels(status="unavailable").set(0 if ready else 1)


def prometheus_payload() -> tuple[bytes, str]:
    """Return the redacted Prometheus exposition payload and content type."""

    # Materialize zero-valued labelled series so dashboards and alerts have a
    # stable shape even before the first recovery or backup event.
    _PROM_COUNTERS["backup_verification"].labels(status="verified").inc(0)
    _PROM_COUNTERS["backup_verification"].labels(status="failed").inc(0)
    _PROM_COUNTERS["orchestration_stalled"].labels(stage="unknown").inc(0)
    _PROM_COUNTERS["recovery_events"].labels(service="unknown", outcome="none").inc(0)
    _PROM_COUNTERS["action_outcome"].labels(outcome="none").inc(0)
    _PROM_STAGE_DURATION.labels(stage="unknown").observe(0)
    if _PROM_POSTGRES_HEALTH.collect()[0].samples == []:
        set_postgres_health(False)
    return generate_latest(_PROMETHEUS), CONTENT_TYPE_LATEST


__all__ = ["METRIC_NAMES", "MetricRegistry", "prometheus_payload", "set_postgres_health"]
