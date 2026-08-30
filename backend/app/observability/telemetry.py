"""Redacted telemetry sink adapters with correlation metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from .correlation import CorrelationContext
from .redaction import redact


class TelemetrySink(Protocol):
    def emit(self, record: dict[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    record_id: str
    kind: str
    occurred_at: str
    attributes: dict[str, str]
    data: dict[str, Any]


class Telemetry:
    """Emit observability metadata; telemetry never participates in correctness."""

    def __init__(self, sink: TelemetrySink) -> None:
        self.sink = sink

    def record(
        self,
        *,
        kind: str,
        context: CorrelationContext,
        data: dict[str, Any] | None = None,
    ) -> TelemetryRecord:
        record = TelemetryRecord(
            record_id=str(uuid4()),
            kind=kind,
            occurred_at=datetime.now(UTC).isoformat(),
            attributes=context.as_attributes(),
            data=redact(data or {}),
        )
        self.sink.emit(asdict(record))
        return record

    def record_model_trace(
        self,
        *,
        context: CorrelationContext,
        data: dict[str, Any],
    ) -> TelemetryRecord:
        return self.record(kind="model_trace", context=context, data=data)

    def record_evaluation(
        self,
        *,
        context: CorrelationContext,
        data: dict[str, Any],
    ) -> TelemetryRecord:
        return self.record(kind="evaluation", context=context, data=data)


class InMemoryTelemetrySink:
    """Test-only sink; it is intentionally not a business-state repository."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def emit(self, record: dict[str, Any]) -> None:
        self.records.append(record)
