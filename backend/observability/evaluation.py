"""Redacted evaluation/model traces with explicit cross-stage correlation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.observability.correlation import CorrelationContext
from app.observability.redaction import REDACTED, redact

EVALUATION_OBSERVABILITY_VERSION = "evaluation-observability-v1.0.0"
_DROP_KEYS = frozenset(
    {
        "raw_payload",
        "raw_evidence",
        "raw_body",
        "plaintext",
        "prompt",
        "scenario",
        "held_out_input",
        "held_out_seed",
        "credentials",
        "secret",
        "password",
        "authorization",
    }
)
_ALLOWED_FIELDS = frozenset(
    {
        "evaluation_run_id",
        "metric_report_id",
        "case_id",
        "tenant_id",
        "correlation_id",
        "mode",
        "label",
        "provider",
        "model",
        "model_version",
        "policy_version",
        "policy_version_id",
        "fixture_version",
        "corpus_version",
        "split",
        "outcome",
        "token_usage",
        "token_count",
        "cost",
        "latency_ms",
        "tool_counts",
        "tool_calls",
        "forbidden_attempts",
        "forbidden_executions",
        "resolution_state",
        "action_reference",
        "audit_reference",
        "provenance_reference",
    }
)
_PROTECTED_FIELDS = frozenset(
    {
        "tenant_id",
        "correlation_id",
        "case_id",
        "evaluation_run_id",
        "metric_report_id",
        "mode",
        "label",
        "live_execution_occurred",
        "non_authoritative",
        "side_effects",
    }
)


def build_evaluation_trace(
    *,
    tenant_id: str,
    correlation_id: str,
    case_id: str | None = None,
    evaluation_run_id: str | None = None,
    metric_report_id: str | None = None,
    mode: str = "replay",
    live_execution_occurred: bool = False,
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded trace record; raw evidence and holdout payloads are dropped."""

    if not tenant_id.strip() or not correlation_id.strip():
        raise ValueError("tenant and correlation identity are required")
    requested_mode = str(mode).strip().lower()
    if requested_mode not in {"live", "replay"}:
        raise ValueError("trace mode must be live or replay")
    effective_mode = "live" if requested_mode == "live" and live_execution_occurred else "replay"
    trace: dict[str, Any] = {
        "observability_version": EVALUATION_OBSERVABILITY_VERSION,
        "recorded_at": datetime.now(UTC).isoformat(),
        "tenant_id": tenant_id,
        "correlation_id": correlation_id,
        "case_id": case_id,
        "evaluation_run_id": evaluation_run_id,
        "metric_report_id": metric_report_id,
        "mode": effective_mode,
        "label": effective_mode,
        "live_execution_occurred": bool(live_execution_occurred and effective_mode == "live"),
        "non_authoritative": True,
        "side_effects": False,
    }
    if requested_mode == "live" and effective_mode == "replay":
        trace["fallback_reason"] = "live execution was not qualified"
    for key, value in (data or {}).items():
        if key in _ALLOWED_FIELDS and key not in _DROP_KEYS and key not in _PROTECTED_FIELDS:
            trace[key] = _redact_trace_value(value)
    trace["trace_correlation"] = {
        "evaluation_run_id": evaluation_run_id,
        "case_id": case_id,
        "correlation_id": correlation_id,
        "metric_report_id": metric_report_id,
    }
    return trace


def redact_evaluation_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Public redaction helper for exporters and test sinks."""

    if not isinstance(value, Mapping):
        raise TypeError("evaluation metadata must be an object")
    return {
        str(key): _redact_trace_value(item)
        for key, item in value.items()
        if str(key).lower() not in _DROP_KEYS
    }


class EvaluationObservability:
    """Best-effort exporter that cannot affect authoritative business state."""

    def __init__(self, sink: Any | None = None, telemetry: Any | None = None) -> None:
        self.sink = sink
        self.telemetry = telemetry

    def record(
        self,
        *,
        tenant_id: str,
        correlation_id: str,
        case_id: str | None = None,
        evaluation_run_id: str | None = None,
        metric_report_id: str | None = None,
        mode: str = "replay",
        live_execution_occurred: bool = False,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace = build_evaluation_trace(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            case_id=case_id,
            evaluation_run_id=evaluation_run_id,
            metric_report_id=metric_report_id,
            mode=mode,
            live_execution_occurred=live_execution_occurred,
            data=data,
        )
        if self.sink is not None:
            try:
                self.sink.emit(dict(trace))
            except Exception:
                # Observability loss cannot alter action correctness or replay
                # outcome. The trace remains available to the caller.
                pass
        if self.telemetry is not None:
            try:
                self.telemetry.record_evaluation(
                    context=CorrelationContext(
                        tenant_id=tenant_id,
                        correlation_id=correlation_id,
                        case_id=case_id,
                    ),
                    data=dict(trace),
                )
            except Exception:
                # Telemetry loss cannot alter action correctness or replay
                # outcome. The trace remains available to the caller.
                pass
        return trace

    record_evaluation = record
    record_model_trace = record


EvaluationTraceRecorder = EvaluationObservability
emit_evaluation_trace = build_evaluation_trace


def record_evaluation_trace(
    *,
    context: CorrelationContext,
    data: Mapping[str, Any] | None = None,
    sink: Any | None = None,
    telemetry: Any | None = None,
) -> dict[str, Any]:
    """Record one redacted evaluation trace using an existing correlation context."""

    return EvaluationObservability(sink=sink, telemetry=telemetry).record(
        tenant_id=context.tenant_id,
        correlation_id=context.correlation_id,
        case_id=context.case_id,
        data=data,
    )


def _redact_trace_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _redact_trace_value(item)
            for key, item in value.items()
            if str(key).lower() not in _DROP_KEYS
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_redact_trace_value(item) for item in value]
    redacted = redact(value)
    if isinstance(redacted, str) and len(redacted) > 512:
        return redacted[:512] + "…"
    return REDACTED if redacted is None and value is not None else redacted


__all__ = [
    "EVALUATION_OBSERVABILITY_VERSION",
    "EvaluationObservability",
    "EvaluationTraceRecorder",
    "build_evaluation_trace",
    "emit_evaluation_trace",
    "record_evaluation_trace",
    "redact_evaluation_metadata",
]
