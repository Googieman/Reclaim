"""Deterministic, side-effect-free timeline reconstruction with optional persistence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.auth.oidc import TenantAuthorizationContext, TenantAuthorizationError
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.timeline_events import build_timeline_rebuilt_event
from evidence.models import CollectedEvidence, NormalizedFact

from .models import TimelineEvent, TimelineRebuildResult

UnitOfWorkFactory = Callable[[TenantAuthorizationContext], PostgresUnitOfWork]


class TimelineReconstructionError(ValueError):
    """Raised when a timeline cannot be built without crossing authority boundaries."""


class TimelineReconstructor:
    """Build the same canonical timeline for the same set of evidence every time."""

    policy_authority = "postgresql"
    authoritative_store = "postgresql"
    event_handoff = "transactional_outbox"
    consumer_count = 0

    def __init__(self, *, unit_of_work_factory: UnitOfWorkFactory | None = None) -> None:
        self.unit_of_work_factory = unit_of_work_factory

    def rebuild(
        self,
        *,
        case_id: str,
        evidence: Iterable[CollectedEvidence],
        normalized_facts: Iterable[NormalizedFact],
        authorization_context: TenantAuthorizationContext,
    ) -> TimelineRebuildResult:
        self._require_authorization(authorization_context)
        if not case_id.strip():
            raise ValueError("case_id is required")
        evidence_items = tuple(evidence)
        facts = tuple(normalized_facts)
        for item in evidence_items:
            self._validate_evidence(item, case_id, authorization_context)
        for fact in facts:
            self._validate_fact(fact, case_id, authorization_context)

        groups: dict[str, list[NormalizedFact]] = defaultdict(list)
        uncertainties: set[str] = set()
        for fact in facts:
            groups[fact.dedupe_key].append(fact)

        events: list[TimelineEvent] = []
        for dedupe_key, candidates in groups.items():
            candidates.sort(key=_selection_key)
            winner = candidates[0]
            source_event_ids = tuple(candidate.source_event_id for candidate in candidates)
            evidence_references = tuple(
                reference for candidate in candidates for reference in candidate.evidence_references
            )
            conflicting_ids = tuple(
                candidate.source_event_id
                for candidate in candidates[1:]
                if _canonical_json(candidate.payload) != _canonical_json(winner.payload)
                or candidate.canonical_event_type != winner.canonical_event_type
            )
            uncertainty_reasons = ("conflicting_sources",) if conflicting_ids else ()
            if conflicting_ids:
                uncertainties.add(f"{dedupe_key}:conflicting_sources")
            events.append(
                TimelineEvent(
                    tenant_id=winner.tenant_id,
                    case_id=winner.case_id,
                    timeline_event_id=_timeline_event_id(
                        tenant_id=winner.tenant_id,
                        case_id=winner.case_id,
                        dedupe_key=dedupe_key,
                    ),
                    canonical_event_type=winner.canonical_event_type,
                    source_event_ids=source_event_ids,
                    source_event_id=winner.source_event_id,
                    source_identity=winner.source_identity,
                    effective_at=winner.effective_at,
                    observed_at=winner.observed_at,
                    received_at=winner.received_at,
                    ordering_key=_ordering_key(winner),
                    dedupe_key=dedupe_key,
                    event_payload=winner.payload,
                    evidence_references=evidence_references,
                    source_priority=winner.source_priority,
                    conflicting_source_event_ids=conflicting_ids,
                    uncertainty_reasons=uncertainty_reasons,
                )
            )

        ordered_events = tuple(sorted(events, key=_event_sort_key))
        if self.unit_of_work_factory is not None:
            self._persist(
                case_id=case_id,
                events=ordered_events,
                authorization_context=authorization_context,
            )
        return TimelineRebuildResult(
            tenant_id=authorization_context.tenant_id,
            case_id=case_id,
            events=ordered_events,
            normalized_facts=tuple(
                sorted(facts, key=_selection_key)
            ),
            uncertainty=uncertainties,
            state="timeline_ready",
            authoritative_store=self.authoritative_store,
            event_handoff=self.event_handoff,
            consumer_count=self.consumer_count,
        )

    def _persist(
        self,
        *,
        case_id: str,
        events: Sequence[TimelineEvent],
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        assert self.unit_of_work_factory is not None
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            for event in events:
                upsert = getattr(unit_of_work.timeline, "upsert", None)
                if upsert is not None:
                    upsert(
                        timeline_event_id=event.timeline_event_id,
                        case_id=case_id,
                        canonical_event_type=event.canonical_event_type,
                        source_event_ids=event.source_event_ids,
                        effective_at=event.effective_at,
                        ordering_key=event.ordering_key,
                        dedupe_key=event.dedupe_key,
                        event_payload=event.event_payload,
                        evidence_references=event.evidence_references,
                    )
                else:
                    unit_of_work.timeline.create(
                        timeline_event_id=event.timeline_event_id,
                        case_id=case_id,
                        canonical_event_type=event.canonical_event_type,
                        source_event_ids=event.source_event_ids,
                        effective_at=event.effective_at,
                        ordering_key=event.ordering_key,
                        dedupe_key=event.dedupe_key,
                        event_payload=event.event_payload,
                        evidence_references=event.evidence_references,
                    )
            transition = getattr(unit_of_work.cases, "transition_state", None)
            if transition is not None:
                transition(case_id=case_id, new_state="timeline_ready")
            event = build_timeline_rebuilt_event(
                TimelineRebuildResult(
                    tenant_id=authorization_context.tenant_id,
                    case_id=case_id,
                    events=tuple(events),
                    normalized_facts=(),
                    state="timeline_ready",
                    authoritative_store=self.authoritative_store,
                    event_handoff=self.event_handoff,
                    consumer_count=self.consumer_count,
                )
            )
            unit_of_work.outbox.enqueue(
                outbox_id=f"outbox-{event.event_id}",
                event=event,
            )

    @staticmethod
    def _validate_evidence(
        item: CollectedEvidence,
        case_id: str,
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        if item.tenant_id != authorization_context.tenant_id or item.case_id != case_id:
            raise TenantAuthorizationError("evidence does not match authorized timeline tenant")

    @staticmethod
    def _validate_fact(
        fact: NormalizedFact,
        case_id: str,
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        if not isinstance(fact, NormalizedFact):
            raise TimelineReconstructionError("timeline input is not a normalized evidence fact")
        if fact.tenant_id != authorization_context.tenant_id or fact.case_id != case_id:
            raise TenantAuthorizationError("timeline fact crosses tenant boundary")
        for value in (fact.effective_at, fact.observed_at, fact.received_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise TimelineReconstructionError("timeline fact timestamp lacks explicit timezone")

    @staticmethod
    def _require_authorization(
        authorization_context: TenantAuthorizationContext,
    ) -> None:
        if not isinstance(authorization_context, TenantAuthorizationContext):
            raise TenantAuthorizationError(
                "timeline reconstruction requires authenticated authorization"
            )


def effective_at(fact: NormalizedFact) -> datetime:
    """Expose the approved event-time precedence rule."""

    candidate = fact.event_at or fact.observed_at or fact.received_at
    if candidate.tzinfo is None or candidate.utcoffset() is None:
        raise TimelineReconstructionError("timeline fact timestamp lacks explicit timezone")
    return candidate.astimezone(UTC)


def _selection_key(fact: NormalizedFact) -> tuple[object, ...]:
    return (
        effective_at(fact),
        fact.source_priority,
        fact.source_identity,
        fact.source_event_id,
        _fact_identity_checksum(fact),
    )


def _event_sort_key(event: TimelineEvent) -> tuple[object, ...]:
    return (
        event.effective_at,
        event.canonical_event_type,
        event.source_identity,
        event.source_event_id,
        event.dedupe_key,
        event.ordering_key,
    )


def _ordering_key(fact: NormalizedFact) -> str:
    return "|".join(
        (
            effective_at(fact).isoformat(),
            fact.canonical_event_type,
            fact.source_identity,
            fact.source_event_id,
            _fact_identity_checksum(fact),
        )
    )


def _timeline_event_id(*, tenant_id: str, case_id: str, dedupe_key: str) -> str:
    identity = f"{tenant_id}|{case_id}|{dedupe_key}".encode()
    return f"timeline-{hashlib.sha256(identity).hexdigest()[:32]}"


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _fact_identity_checksum(fact: NormalizedFact) -> str:
    """Return the canonical final key for otherwise indistinguishable facts."""

    identity: dict[str, Any] = {
        "tenant_id": fact.tenant_id,
        "case_id": fact.case_id,
        "evidence_id": fact.evidence_id,
        "resource_type": fact.resource_type,
        "source_identity": fact.source_identity,
        "source_event_id": fact.source_event_id,
        "canonical_event_type": fact.canonical_event_type,
        "dedupe_key": fact.dedupe_key,
        "effective_at": effective_at(fact).isoformat(),
        "observed_at": fact.observed_at.astimezone(UTC).isoformat(),
        "received_at": fact.received_at.astimezone(UTC).isoformat(),
        "event_at": None if fact.event_at is None else fact.event_at.astimezone(UTC).isoformat(),
        "source_priority": fact.source_priority,
        "payload": fact.payload,
        "provider_identifiers": fact.provider_identifiers,
        "original_timestamps": fact.original_timestamps,
        "evidence_references": fact.evidence_references,
    }
    return hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


__all__ = [
    "TimelineReconstructionError",
    "TimelineReconstructor",
    "effective_at",
]
