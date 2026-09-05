"""Versioned Action Gateway and terminal events."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from packages.contracts.events import EventEnvelope, EventType

from .authority import payload_checksum


class ActionEventKind(StrEnum):
    REQUESTED = EventType.ACTION_REQUESTED.value
    UNKNOWN = EventType.ACTION_UNKNOWN.value
    RECONCILED = EventType.ACTION_RECONCILED.value
    VERIFICATION_COMPLETED = EventType.VERIFICATION_COMPLETED.value
    CASE_ESCALATED = EventType.CASE_ESCALATED.value
    CASE_TERMINAL = EventType.CASE_TERMINAL.value


def build_action_event(
    *,
    event_type: EventType | ActionEventKind | str,
    tenant_id: str,
    case_id: str,
    correlation_id: str,
    causation_id: str,
    payload: dict[str, Any],
    aggregate_id: str | None = None,
    occurred_at: datetime | None = None,
    producer: str = "action-gateway@1.0.0",
) -> EventEnvelope:
    try:
        event = EventType(event_type)
    except ValueError as exc:
        raise ValueError("unsupported action event type") from exc
    allowed = {
        EventType.ACTION_REQUESTED,
        EventType.ACTION_UNKNOWN,
        EventType.ACTION_RECONCILED,
        EventType.VERIFICATION_COMPLETED,
        EventType.CASE_ESCALATED,
        EventType.CASE_TERMINAL,
    }
    if event not in allowed:
        raise ValueError("event type is outside the action lifecycle")
    safe_payload = _safe_payload(payload)
    when = _utc(occurred_at or datetime.now(UTC))
    event_id = f"{event.value}:{aggregate_id or case_id}:{payload_checksum(safe_payload)}"
    return EventEnvelope(
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        event_id=event_id,
        event_type=event,
        aggregate_type="case",
        aggregate_id=aggregate_id or case_id,
        occurred_at=when,
        produced_at=when,
        causation_id=causation_id,
        producer=producer,
        payload_checksum=payload_checksum(safe_payload),
        payload=safe_payload,
    )


def build_case_terminal_event(transition: Any, *, audit_reference: str) -> EventEnvelope:
    return build_action_event(
        event_type=EventType.CASE_TERMINAL,
        tenant_id=transition.tenant_id,
        case_id=transition.case_id,
        correlation_id=transition.correlation_ids[0]
        if transition.correlation_ids
        else transition.case_id,
        causation_id=transition.execution_id or transition.case_id,
        payload={
            "tenant_id": transition.tenant_id,
            "case_id": transition.case_id,
            "terminal_state": transition.state,
            "action_id": transition.action_id,
            "execution_id": transition.execution_id,
            "verification_id": transition.verification_id,
            "escalation_id": transition.escalation_id,
            "remaining_exposure_minor": transition.remaining_exposure_minor,
            "currency": transition.currency,
            "audit_reference": audit_reference,
        },
    )


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("action event payload must be an object")
    forbidden = {
        "secret",
        "credential",
        "token",
        "password",
        "raw",
        "authorization",
        "email",
        "phone",
        "pii",
    }

    def safe_value(value: Any) -> Any:
        if isinstance(value, dict):
            safe: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(part in lowered for part in forbidden):
                    raise ValueError(
                        "action event payload contains a secret or raw sensitive field"
                    )
                safe[str(key)] = safe_value(item)
            return safe
        if isinstance(value, list):
            return [safe_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(safe_value(item) for item in value)
        return value

    return safe_value(payload)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("action event timestamp must include timezone")
    return value.astimezone(UTC)


__all__ = ["ActionEventKind", "build_action_event", "build_case_terminal_event"]
