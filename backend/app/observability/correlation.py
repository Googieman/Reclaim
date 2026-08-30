"""Cross-service correlation identifiers safe for telemetry attributes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    tenant_id: str
    correlation_id: str
    case_id: str | None = None
    workflow_id: str | None = None
    action_id: str | None = None
    event_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("tenant_id", "correlation_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
        for name in ("case_id", "workflow_id", "action_id", "event_id", "causation_id"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} cannot be blank")

    def as_attributes(self) -> dict[str, str]:
        return {
            f"reclaim.{name}": value
            for name in (
                "tenant_id",
                "correlation_id",
                "case_id",
                "workflow_id",
                "action_id",
                "event_id",
                "causation_id",
            )
            if (value := getattr(self, name)) is not None
        }
