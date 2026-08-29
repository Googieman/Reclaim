from datetime import datetime, timezone

from packages.contracts.events import EventEnvelope, EventType


def test_event_envelope_carries_delivery_and_correlation_metadata() -> None:
    event = EventEnvelope(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        event_id="event-1",
        event_type=EventType.INCIDENT_ACCEPTED,
        aggregate_type="incident",
        aggregate_id="incident-1",
        occurred_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        produced_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        causation_id="command-1",
        producer="intake-api@1.0.0",
        payload_checksum="sha256:payload",
        payload={"source": "operator"},
    )
    assert event.event_type == "incident.accepted"
    assert event.occurred_at.tzinfo == timezone.utc
