"""Immutable timeline values with explicit provenance and uncertainty."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    tenant_id: str
    case_id: str
    timeline_event_id: str
    canonical_event_type: str
    source_event_ids: tuple[str, ...]
    source_event_id: str
    source_identity: str
    effective_at: datetime
    observed_at: datetime
    received_at: datetime
    ordering_key: str
    dedupe_key: str
    event_payload: Mapping[str, Any]
    evidence_references: tuple[str, ...]
    source_priority: int = 100
    conflicting_source_event_ids: tuple[str, ...] = ()
    uncertainty_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "case_id",
            "timeline_event_id",
            "canonical_event_type",
            "source_event_id",
            "source_identity",
            "ordering_key",
            "dedupe_key",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"timeline event {name} is required")
        for name in ("effective_at", "observed_at", "received_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"timeline event {name} requires explicit timezone")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.source_priority < 0:
            raise ValueError("timeline event source priority cannot be negative")
        object.__setattr__(self, "source_event_ids", tuple(sorted(set(self.source_event_ids))))
        object.__setattr__(self, "event_payload", dict(self.event_payload))
        object.__setattr__(
            self,
            "evidence_references",
            tuple(sorted(set(self.evidence_references))),
        )
        object.__setattr__(
            self,
            "conflicting_source_event_ids",
            tuple(sorted(set(self.conflicting_source_event_ids))),
        )
        object.__setattr__(
            self,
            "uncertainty_reasons",
            tuple(sorted(set(self.uncertainty_reasons))),
        )


@dataclass(frozen=True, slots=True)
class TimelineRebuildResult:
    tenant_id: str
    case_id: str
    events: tuple[TimelineEvent, ...]
    normalized_facts: tuple[Any, ...] = ()
    uncertainty: tuple[str, ...] = ()
    state: str = "timeline_ready"
    authoritative_store: str = "postgresql"
    event_handoff: str = "transactional_outbox"
    consumer_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "normalized_facts", tuple(self.normalized_facts))
        object.__setattr__(self, "uncertainty", tuple(sorted(set(self.uncertainty))))
