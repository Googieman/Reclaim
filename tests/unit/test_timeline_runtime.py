"""Production timeline determinism and conflict handling tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from itertools import permutations

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType, TenantAuthorizationError
from evidence.models import CollectedEvidence, NormalizedFact
from timeline.reconstruct import TimelineReconstructor


def context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="reviewer-1",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"reviewer"})},
        identity_type=IdentityType.USER,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


def fact(
    *,
    dedupe_key: str,
    source_event_id: str,
    event_type: str,
    effective_at: datetime,
    source_identity: str = "merchant-store",
    source_priority: int = 100,
    payload: dict[str, object] | None = None,
) -> NormalizedFact:
    return NormalizedFact(
        tenant_id="tenant-a",
        case_id="case-1",
        evidence_id=f"evidence-{source_event_id}",
        resource_type="payments",
        source_identity=source_identity,
        source_event_id=source_event_id,
        canonical_event_type=event_type,
        dedupe_key=dedupe_key,
        effective_at=effective_at,
        observed_at=effective_at,
        received_at=effective_at + timedelta(minutes=1),
        event_at=effective_at,
        source_priority=source_priority,
        payload=payload or {"source_event_id": source_event_id},
        evidence_references=(f"evidence-{source_event_id}",),
    )


class PersistedTimeline:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def upsert(self, **values: object) -> object:
        self.rows.append(values)
        return values


class PersistedCase:
    def __init__(self) -> None:
        self.uncertainty: tuple[str, ...] | None = None
        self.states: list[str] = []

    def set_timeline_uncertainty(
        self, *, case_id: str, uncertainty: tuple[str, ...]
    ) -> object:
        self.uncertainty = uncertainty
        return ("tenant-a", case_id, "incident-1", "uncertainty-updated")

    def transition_state(self, *, case_id: str, new_state: str) -> object:
        self.states.append(new_state)
        return ("tenant-a", case_id, "incident-1", new_state)


class PersistedOutbox:
    def __init__(self) -> None:
        self.events: list[object] = []

    def enqueue(self, *, outbox_id: str, event: object) -> object:
        self.events.append(event)
        return event


class PersistedTimelineUnitOfWork:
    def __init__(self) -> None:
        self.timeline = PersistedTimeline()
        self.cases = PersistedCase()
        self.outbox = PersistedOutbox()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


def collected_evidence(
    *,
    completeness: str = "complete",
    normalization_status: str = "normalized",
    integrity_status: str = "verified",
    collection_error: str | None = None,
) -> CollectedEvidence:
    timestamp = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    return CollectedEvidence(
        tenant_id="tenant-a",
        case_id="case-1",
        correlation_id="corr-1",
        evidence_id="evidence-1",
        connector_id="payments",
        resource_type="payments",
        source_identifier="payments-1",
        source_identity="merchant-ledger",
        observed_at=timestamp,
        received_at=timestamp,
        raw_object_uri="minio://evidence-1",
        raw_checksum="sha256:evidence-1",
        expected_checksum="sha256:evidence-1",
        completeness=completeness,
        normalization_status=normalization_status,
        integrity_status=integrity_status,
        collection_error=collection_error,
    )


def persisted_reconstructor() -> (
    tuple[TimelineReconstructor, PersistedTimelineUnitOfWork]
):
    unit_of_work = PersistedTimelineUnitOfWork()
    return (
        TimelineReconstructor(unit_of_work_factory=lambda _context: unit_of_work),
        unit_of_work,
    )


def test_duplicate_and_out_of_order_production_reconstruction_converges() -> None:
    base = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
    canonical = (
        fact(
            dedupe_key="session:s-1",
            source_event_id="session-event",
            event_type="session.opened",
            effective_at=base,
        ),
        fact(
            dedupe_key="payment:p-1",
            source_event_id="payment-event",
            event_type="payment.captured",
            effective_at=base + timedelta(minutes=2),
        ),
        fact(
            dedupe_key="order:o-1",
            source_event_id="order-event",
            event_type="order.created",
            effective_at=base + timedelta(minutes=3),
        ),
    )
    reconstructor = TimelineReconstructor()
    expected = reconstructor.rebuild(
        case_id="case-1",
        evidence=(),
        normalized_facts=canonical,
        authorization_context=context(),
    )

    for ordering in permutations(canonical + (canonical[1], canonical[0])):
        result = reconstructor.rebuild(
            case_id="case-1",
            evidence=(),
            normalized_facts=ordering,
            authorization_context=context(),
        )
        assert result.events == expected.events
        assert len({event.dedupe_key for event in result.events}) == len(result.events)


def test_equal_timestamps_use_stable_type_source_and_event_id_order() -> None:
    timestamp = datetime(
        2026, 8, 30, 13, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    reconstructor = TimelineReconstructor()
    result = reconstructor.rebuild(
        case_id="case-1",
        evidence=(),
        normalized_facts=(
            fact(
                dedupe_key="session:s-1",
                source_event_id="z-event",
                event_type="session.opened",
                effective_at=timestamp,
            ),
            fact(
                dedupe_key="order:o-1",
                source_event_id="a-event",
                event_type="order.created",
                effective_at=timestamp,
            ),
        ),
        authorization_context=context(),
    )

    assert [event.dedupe_key for event in result.events] == ["order:o-1", "session:s-1"]
    assert all(
        event.effective_at == datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
        for event in result.events
    )


def test_conflicting_sources_choose_stably_and_surface_uncertainty() -> None:
    timestamp = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    reconstructor = TimelineReconstructor()
    provider = fact(
        dedupe_key="payment:p-1",
        source_event_id="provider-1",
        event_type="payment.captured",
        effective_at=timestamp,
        source_identity="razorpay-test",
        source_priority=10,
        payload={"status": "captured"},
    )
    fallback = fact(
        dedupe_key="payment:p-1",
        source_event_id="fallback-1",
        event_type="payment.captured",
        effective_at=timestamp,
        source_identity="merchant-ledger",
        source_priority=20,
        payload={"status": "authorized"},
    )

    first = reconstructor.rebuild(
        case_id="case-1",
        evidence=(),
        normalized_facts=(fallback, provider),
        authorization_context=context(),
    )
    second = reconstructor.rebuild(
        case_id="case-1",
        evidence=(),
        normalized_facts=(provider, fallback),
        authorization_context=context(),
    )

    assert first.events == second.events
    assert first.events[0].source_event_id == "provider-1"
    assert first.events[0].conflicting_source_event_ids == ("fallback-1",)
    assert first.uncertainty == ("payment:p-1:conflicting_sources",)


def test_persistence_and_outbox_retain_conflict_uncertainty_and_replay_is_equal() -> (
    None
):
    timestamp = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    provider = fact(
        dedupe_key="payment:p-1",
        source_event_id="provider-1",
        event_type="payment.captured",
        effective_at=timestamp,
        source_identity="razorpay-test",
        source_priority=10,
        payload={"status": "captured"},
    )
    fallback = fact(
        dedupe_key="payment:p-1",
        source_event_id="fallback-1",
        event_type="payment.captured",
        effective_at=timestamp,
        source_identity="merchant-ledger",
        source_priority=20,
        payload={"status": "authorized"},
    )

    first_reconstructor, first_uow = persisted_reconstructor()
    first = first_reconstructor.rebuild(
        case_id="case-1",
        evidence=(),
        normalized_facts=(fallback, provider),
        authorization_context=context(),
    )
    first_event = first_uow.outbox.events[0]

    second_reconstructor, second_uow = persisted_reconstructor()
    second = second_reconstructor.rebuild(
        case_id="case-1",
        evidence=(),
        normalized_facts=(provider, fallback),
        authorization_context=context(),
    )
    second_event = second_uow.outbox.events[0]

    assert first.uncertainty == ("payment:p-1:conflicting_sources",)
    assert first_uow.cases.uncertainty == first.uncertainty
    assert first_uow.timeline.rows[0]["conflicting_source_event_ids"] == ("fallback-1",)
    assert first_uow.timeline.rows[0]["uncertainty_reasons"] == ("conflicting_sources",)
    assert first_event.payload["uncertainty"] == list(first.uncertainty)
    assert first_event.payload == second_event.payload
    assert first_event.payload_checksum == second_event.payload_checksum
    assert second.uncertainty == first.uncertainty


def test_partial_or_unavailable_evidence_remains_uncertain_without_facts() -> None:
    reconstructor, unit_of_work = persisted_reconstructor()

    result = reconstructor.rebuild(
        case_id="case-1",
        evidence=(
            collected_evidence(
                completeness="partial",
                normalization_status="not_attempted",
                integrity_status="not_verified",
                collection_error="connector unavailable",
            ),
        ),
        normalized_facts=(),
        authorization_context=context(),
    )
    event = unit_of_work.outbox.events[0]

    assert result.events == ()
    assert result.uncertainty == (
        "payments:completeness=partial",
        "payments:connector unavailable",
        "payments:integrity=not_verified",
        "payments:normalization=not_attempted",
    )
    assert unit_of_work.cases.uncertainty == result.uncertainty
    assert event.payload["uncertainty"] == list(result.uncertainty)


def test_complete_evidence_without_conflict_has_no_uncertainty() -> None:
    reconstructor, unit_of_work = persisted_reconstructor()

    result = reconstructor.rebuild(
        case_id="case-1",
        evidence=(collected_evidence(),),
        normalized_facts=(),
        authorization_context=context(),
    )

    assert result.uncertainty == ()
    assert unit_of_work.cases.uncertainty == ()
    assert unit_of_work.outbox.events[0].payload["uncertainty"] == []


def test_exact_tie_conflicts_converge_for_every_adversarial_arrival_order() -> None:
    timestamp = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    first = fact(
        dedupe_key="payment:p-1",
        source_event_id="same-event",
        event_type="payment.captured",
        effective_at=timestamp,
        source_identity="same-source",
        source_priority=10,
        payload={"status": "captured", "amount": 100},
    )
    second = replace(
        first,
        evidence_id="evidence-second",
        payload={"status": "authorized", "amount": 100},
        evidence_references=("evidence-second",),
    )
    candidates = (first, second)
    reconstructor = TimelineReconstructor()
    expected = reconstructor.rebuild(
        case_id="case-1",
        evidence=(),
        normalized_facts=candidates,
        authorization_context=context(),
    )

    for ordering in permutations(candidates):
        result = reconstructor.rebuild(
            case_id="case-1",
            evidence=(),
            normalized_facts=ordering,
            authorization_context=context(),
        )
        assert result.events == expected.events
        assert result.events[0].source_event_id == "same-event"
        assert result.events[0].event_payload == expected.events[0].event_payload


def test_final_event_order_is_deterministic_when_existing_sort_keys_are_equal() -> None:
    timestamp = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    events = (
        fact(
            dedupe_key="payment:z-1",
            source_event_id="same-event",
            event_type="payment.captured",
            effective_at=timestamp,
            source_identity="same-source",
        ),
        fact(
            dedupe_key="payment:a-1",
            source_event_id="same-event",
            event_type="payment.captured",
            effective_at=timestamp,
            source_identity="same-source",
        ),
    )
    reconstructor = TimelineReconstructor()

    first = reconstructor.rebuild(
        case_id="case-1",
        evidence=(),
        normalized_facts=events,
        authorization_context=context(),
    )
    second = reconstructor.rebuild(
        case_id="case-1",
        evidence=(),
        normalized_facts=tuple(reversed(events)),
        authorization_context=context(),
    )

    assert first.events == second.events
    assert [event.dedupe_key for event in first.events] == [
        "payment:a-1",
        "payment:z-1",
    ]


def test_timeline_rejects_cross_tenant_fact_even_when_request_context_matches_it() -> (
    None
):
    bad_fact = fact(
        dedupe_key="payment:p-1",
        source_event_id="payment-event",
        event_type="payment.captured",
        effective_at=datetime(2026, 8, 30, 8, 0, tzinfo=UTC),
    )
    bad_fact = replace(bad_fact, tenant_id="tenant-b")

    with pytest.raises(TenantAuthorizationError):
        TimelineReconstructor().rebuild(
            case_id="case-1",
            evidence=(),
            normalized_facts=(bad_fact,),
            authorization_context=context("tenant-a"),
        )
