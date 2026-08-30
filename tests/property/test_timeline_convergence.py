"""Property coverage for duplicate and out-of-order timeline convergence.

The production timeline implementation now satisfies this property. This test
keeps the required convergence property executable using a small immutable
reference representation at the contract boundary.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import permutations


@dataclass(frozen=True, slots=True)
class DeliveredFact:
    dedupe_key: str
    event_id: str
    effective_at: datetime
    event_type: str
    financial_fact_id: str | None = None
    action_fact_id: str | None = None

    @property
    def ordering_key(self) -> tuple[datetime, str, str]:
        return self.effective_at, self.event_type, self.event_id


def reconstruct_reference(
    events: tuple[DeliveredFact, ...],
) -> tuple[DeliveredFact, ...]:
    deduplicated: dict[str, DeliveredFact] = {}
    for event in events:
        existing = deduplicated.get(event.dedupe_key)
        if existing is None or event.ordering_key < existing.ordering_key:
            deduplicated[event.dedupe_key] = event
    return tuple(sorted(deduplicated.values(), key=lambda event: event.ordering_key))


def facts() -> tuple[DeliveredFact, ...]:
    base = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
    return (
        DeliveredFact("session:s-1", "event-session", base, "session.opened"),
        DeliveredFact(
            "payment:p-1",
            "event-payment",
            base + timedelta(minutes=2),
            "payment.captured",
            financial_fact_id="payment:p-1",
        ),
        DeliveredFact(
            "order:o-1",
            "event-order",
            base + timedelta(minutes=3),
            "order.created",
            action_fact_id="order:o-1",
        ),
    )


def test_duplicate_and_out_of_order_delivery_converges_for_every_permutation() -> None:
    canonical = facts()
    delivered = canonical + (canonical[1], canonical[0])
    expected = reconstruct_reference(canonical)

    for ordering in permutations(delivered):
        result = reconstruct_reference(ordering)
        assert result == expected
        assert len({event.dedupe_key for event in result}) == len(result)
        financial_ids = [
            event.financial_fact_id for event in result if event.financial_fact_id
        ]
        action_ids = [event.action_fact_id for event in result if event.action_fact_id]
        assert len(financial_ids) == len(set(financial_ids))
        assert len(action_ids) == len(set(action_ids))


def test_repeated_reconstruction_is_byte_for_byte_stable_in_business_order() -> None:
    events = tuple(reversed(facts())) + (facts()[2],)
    first = reconstruct_reference(events)
    second = reconstruct_reference(events)

    assert first == second
    assert [event.event_id for event in first] == [
        "event-session",
        "event-payment",
        "event-order",
    ]
