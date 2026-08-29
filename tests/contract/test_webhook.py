from datetime import datetime, timezone

import pytest

from packages.contracts.intake import (
    IntakeStatus,
    RazorpayWebhookRequest,
    WebhookProcessingResponse,
)


def test_webhook_preserves_original_bytes_checksum_and_provider_identity() -> None:
    request = RazorpayWebhookRequest(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        connector_id="razorpay-test",
        original_payload=b'{"event":"payment.captured"}',
        payload_checksum="sha256:payload",
        signature="signature",
        provider_event_id="evt-1",
        event_type="payment.captured",
        event_timestamp=datetime(2026, 8, 30, tzinfo=timezone.utc),
        received_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    assert request.original_payload.startswith(b"{")
    assert request.provider_event_id == "evt-1"


def test_incomplete_webhook_can_be_quarantined_but_accepted_needs_identity() -> None:
    quarantined = WebhookProcessingResponse(
        tenant_id="tenant-a",
        correlation_id="corr-1",
        status=IntakeStatus.QUARANTINED,
        connector_id="razorpay-test",
        reason="missing provider event identity",
    )
    assert quarantined.status == "quarantined"
    with pytest.raises(ValueError, match="provider_event_id"):
        WebhookProcessingResponse(
            tenant_id="tenant-a",
            correlation_id="corr-1",
            status=IntakeStatus.ACCEPTED,
            connector_id="razorpay-test",
        )
