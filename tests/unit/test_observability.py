"""Redacted telemetry and correlation tests."""

from app.observability import CorrelationContext, Telemetry, redact
from app.observability.telemetry import InMemoryTelemetrySink


def test_telemetry_preserves_correlation_and_redacts_sensitive_values() -> None:
    sink = InMemoryTelemetrySink()
    telemetry = Telemetry(sink)
    context = CorrelationContext(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        case_id="case-1",
        workflow_id="workflow-1",
        event_id="event-1",
    )
    record = telemetry.record_model_trace(
        context=context,
        data={
            "prompt": {"email": "user@example.invalid", "tenant_id": "tenant-a"},
            "token": "secret",
        },
    )

    assert record.attributes["reclaim.tenant_id"] == "tenant-a"
    assert sink.records[0]["data"]["prompt"]["email"] == "[REDACTED]"
    assert sink.records[0]["data"]["prompt"]["tenant_id"] == "tenant-a"
    assert redact({"authorization": "Bearer secret"})["authorization"] == "[REDACTED]"
