"""Unit coverage for the deterministic timeline reconstruction contract.

The production timeline service preserves this executable contract oracle. The
precedence and tie-breaking rules remain explicit so arrival order cannot become
authoritative silently.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest


@dataclass(frozen=True, slots=True)
class SourceTimelineEvent:
    dedupe_key: str
    source_event_id: str
    canonical_event_type: str
    source_identity: str
    received_at: datetime
    observed_at: datetime | None = None
    event_at: datetime | None = None
    source_priority: int = 100
    payload: tuple[tuple[str, str], ...] = ()


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include an explicit timezone")
    return value.astimezone(UTC)


def effective_at(event: SourceTimelineEvent) -> datetime:
    for candidate in (event.event_at, event.observed_at, event.received_at):
        if candidate is not None:
            return normalize_utc(candidate)
    raise ValueError("timeline event requires a timestamp")


def reconstruct_reference(
    events: tuple[SourceTimelineEvent, ...],
) -> tuple[SourceTimelineEvent, ...]:
    selected: dict[str, SourceTimelineEvent] = {}
    for event in events:
        current = selected.get(event.dedupe_key)
        selection_key = (
            effective_at(event),
            event.source_priority,
            event.source_identity,
            event.source_event_id,
        )
        if current is None or selection_key < (
            effective_at(current),
            current.source_priority,
            current.source_identity,
            current.source_event_id,
        ):
            selected[event.dedupe_key] = event
    return tuple(
        sorted(
            selected.values(),
            key=lambda event: (
                effective_at(event),
                event.canonical_event_type,
                event.source_identity,
                event.source_event_id,
            ),
        )
    )


def base_event(**overrides: object) -> SourceTimelineEvent:
    values: dict[str, object] = {
        "dedupe_key": "payment:p-1",
        "source_event_id": "provider-1",
        "canonical_event_type": "payment.captured",
        "source_identity": "razorpay-test",
        "received_at": datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return SourceTimelineEvent(**values)


def test_timestamp_precedence_is_event_time_then_observed_then_received() -> None:
    event_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    observed_time = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
    received_time = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)

    assert (
        effective_at(
            base_event(
                event_at=event_time,
                observed_at=observed_time,
                received_at=received_time,
            )
        )
        == event_time
    )
    assert (
        effective_at(base_event(event_at=None, observed_at=observed_time))
        == observed_time
    )
    assert effective_at(base_event(event_at=None, observed_at=None)) == received_time


def test_all_accepted_timestamps_are_normalized_to_utc_and_naive_time_is_rejected() -> (
    None
):
    local_time = datetime(
        2026, 8, 30, 13, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )

    assert effective_at(base_event(event_at=local_time)) == datetime(
        2026, 8, 30, 8, 0, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="explicit timezone"):
        effective_at(base_event(event_at=datetime.fromisoformat("2026-08-30T08:00:00")))


def test_equal_timestamps_use_stable_type_source_and_event_id_tie_breaking() -> None:
    timestamp = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    events = (
        base_event(
            dedupe_key="session:s-1",
            source_event_id="z-event",
            canonical_event_type="session.opened",
            source_identity="merchant-session-store",
            event_at=timestamp,
        ),
        base_event(
            dedupe_key="order:o-1",
            source_event_id="a-event",
            canonical_event_type="order.created",
            source_identity="merchant-order-store",
            event_at=timestamp,
        ),
    )

    first = reconstruct_reference(events)
    second = reconstruct_reference(tuple(reversed(events)))

    assert first == second
    assert [event.dedupe_key for event in first] == ["order:o-1", "session:s-1"]


def test_duplicate_dedupe_key_merges_to_one_timeline_fact() -> None:
    event = base_event(event_at=datetime(2026, 8, 30, 8, 0, tzinfo=UTC))
    duplicate = base_event(source_event_id="provider-1-retry", event_at=event.event_at)

    result = reconstruct_reference((duplicate, event, duplicate))

    assert len(result) == 1
    assert result[0].dedupe_key == "payment:p-1"
    assert result[0].source_event_id == "provider-1"


def test_conflicting_sources_have_deterministic_preferred_source() -> None:
    timestamp = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    provider = base_event(
        source_event_id="provider-1",
        source_identity="razorpay-test",
        source_priority=10,
        event_at=timestamp,
        payload=(("status", "captured"),),
    )
    fallback = base_event(
        source_event_id="fallback-1",
        source_identity="merchant-ledger",
        source_priority=20,
        event_at=timestamp,
        payload=(("status", "authorized"),),
    )

    assert reconstruct_reference((fallback, provider)) == reconstruct_reference(
        (provider, fallback)
    )
    assert (
        reconstruct_reference((fallback, provider))[0].source_identity
        == "razorpay-test"
    )
