"""Typed, provenance-preserving values used by advisory attribution.

The shared ``AttributionSuggestion`` contract intentionally stays provider-neutral.
These values carry the tenant/case and authoritative timeline input alongside that
contract so an attribution cannot be detached from the case it analyzed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from packages.contracts.analysis_policy import AttributionLabel, AttributionSuggestion

_MISSING = object()


def _value(value: object, name: str, default: object = _MISSING) -> object:
    if isinstance(value, Mapping):
        result = value.get(name, default)
    else:
        result = getattr(value, name, default)
    if result is _MISSING:
        raise ValueError(f"attribution input {name} is required")
    return result


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"attribution input {name} is required")
    return value.strip()


def _references(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str | bytes):
        raise ValueError(f"attribution input {name} must be a sequence")
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"attribution input {name} must be a sequence") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"attribution input {name} contains an invalid reference")
    return tuple(sorted(set(item.strip() for item in values)))


@dataclass(frozen=True, slots=True)
class AttributionInput:
    """The immutable authoritative input used for one event assessment."""

    tenant_id: str
    case_id: str
    timeline_event_id: str
    canonical_event_type: str
    event_payload: Mapping[str, Any]
    evidence_references: tuple[str, ...]
    source_event_ids: tuple[str, ...] = ()
    conflicting_source_event_ids: tuple[str, ...] = ()
    uncertainty_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "case_id",
            "timeline_event_id",
            "canonical_event_type",
        ):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        object.__setattr__(self, "event_payload", dict(self.event_payload))
        object.__setattr__(
            self,
            "evidence_references",
            _references(self.evidence_references, "evidence_references"),
        )
        object.__setattr__(
            self, "source_event_ids", _references(self.source_event_ids, "source_event_ids")
        )
        object.__setattr__(
            self,
            "conflicting_source_event_ids",
            _references(self.conflicting_source_event_ids, "conflicting_source_event_ids"),
        )
        object.__setattr__(
            self,
            "uncertainty_reasons",
            _references(self.uncertainty_reasons, "uncertainty_reasons"),
        )

    @property
    def input_references(self) -> tuple[str, ...]:
        """Return stable references to every authoritative input identifier."""

        return tuple(
            sorted(
                {
                    self.timeline_event_id,
                    *self.source_event_ids,
                    *self.evidence_references,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class AttributionRecord:
    """An attribution suggestion bound to the case and its authoritative input."""

    input: AttributionInput
    suggestion: AttributionSuggestion
    analysis_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.suggestion.timeline_event_id != self.input.timeline_event_id:
            raise ValueError("attribution suggestion does not match timeline input")
        if not set(self.suggestion.evidence_references).issubset(
            set(self.input.evidence_references)
        ):
            raise ValueError("attribution suggestion references unknown evidence")
        if self.analysis_version is not None and not self.analysis_version.strip():
            raise ValueError("attribution analysis version cannot be empty")
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def tenant_id(self) -> str:
        return self.input.tenant_id

    @property
    def case_id(self) -> str:
        return self.input.case_id

    @property
    def input_references(self) -> tuple[str, ...]:
        return self.input.input_references

    @property
    def timeline_event_id(self) -> str:
        return self.suggestion.timeline_event_id

    @property
    def label(self) -> AttributionLabel:
        return self.suggestion.label

    @property
    def confidence(self) -> float:
        return self.suggestion.confidence

    @property
    def rationale(self) -> str:
        return self.suggestion.rationale

    @property
    def evidence_references(self) -> tuple[str, ...]:
        return self.suggestion.evidence_references

    @property
    def method(self) -> str:
        return self.suggestion.method

    @property
    def model_or_rules_version(self) -> str:
        return self.suggestion.model_or_rules_version

    def as_suggestion(self) -> AttributionSuggestion:
        return self.suggestion


def attribution_input_from_event(event: object) -> AttributionInput:
    """Convert a timeline value into the explicit attribution input boundary."""

    payload = _value(event, "event_payload", _MISSING)
    if payload is _MISSING:
        payload = _value(event, "payload", {})
    if not isinstance(payload, Mapping):
        raise ValueError("attribution event payload must be an object")
    return AttributionInput(
        tenant_id=_required_text(_value(event, "tenant_id"), "tenant_id"),
        case_id=_required_text(_value(event, "case_id"), "case_id"),
        timeline_event_id=_required_text(_value(event, "timeline_event_id"), "timeline_event_id"),
        canonical_event_type=_required_text(
            _value(event, "canonical_event_type"), "canonical_event_type"
        ),
        event_payload=payload,
        evidence_references=_references(
            _value(event, "evidence_references", ()), "evidence_references"
        ),
        source_event_ids=_references(_value(event, "source_event_ids", ()), "source_event_ids"),
        conflicting_source_event_ids=_references(
            _value(event, "conflicting_source_event_ids", ()),
            "conflicting_source_event_ids",
        ),
        uncertainty_reasons=_references(
            _value(event, "uncertainty_reasons", ()), "uncertainty_reasons"
        ),
    )


__all__ = [
    "AttributionInput",
    "AttributionRecord",
    "attribution_input_from_event",
]
