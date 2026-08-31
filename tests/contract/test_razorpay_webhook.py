"""Contract coverage for authenticated Razorpay Test Mode webhook intake."""

import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from packages.contracts.intake import (
    IntakeStatus,
    RazorpayWebhookRequest,
    VerifiedProviderCorrelation,
    VerifiedProviderVerification,
    WebhookProcessingResponse,
)

PAYLOAD = b'{"entity":"event","id":"evt_1","type":"payment.captured"}'


def payload_checksum(payload: bytes = PAYLOAD) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def make_webhook(**overrides: object) -> RazorpayWebhookRequest:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "correlation_id": "corr-webhook-1",
        "connector_id": "razorpay-test",
        "original_payload": PAYLOAD,
        "payload_checksum": payload_checksum(),
        "signature": "test-mode-signature",
        "provider_event_id": "evt_1",
        "event_type": "payment.captured",
        "event_timestamp": datetime(2026, 8, 30, 9, 0, tzinfo=UTC),
        "received_at": datetime(2026, 8, 30, 9, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return RazorpayWebhookRequest(**values)


def verified_correlation() -> VerifiedProviderCorrelation:
    return VerifiedProviderCorrelation(
        provider="razorpay",
        connector_id="razorpay-test",
        provider_event_id="evt_1",
        provider_payment_id="pay_1",
        verification=VerifiedProviderVerification(
            state="verified",
            method="hmac-sha256-original-payload",
            provenance="secret/data/tenants/tenant-a/connectors/razorpay-test/webhook",
            payload_checksum=payload_checksum(),
            verifier_version="razorpay-webhook-verifier@2.0.0",
            verified_at=datetime(2026, 8, 30, 9, 1, tzinfo=UTC),
        ),
    )


def test_webhook_preserves_original_bytes_and_declared_checksum_for_verification() -> (
    None
):
    request = make_webhook()

    assert request.original_payload == PAYLOAD
    assert request.payload_checksum == payload_checksum(PAYLOAD)
    assert request.provider_event_id == "evt_1"
    assert request.event_timestamp == datetime(2026, 8, 30, 9, 0, tzinfo=UTC)


def test_webhook_contract_rejects_empty_payload_and_naive_timestamps() -> None:
    with pytest.raises(ValidationError):
        make_webhook(original_payload=b"")
    with pytest.raises(ValidationError, match="timezone"):
        make_webhook(received_at=datetime.fromisoformat("2026-08-30T09:01:00"))
    with pytest.raises(ValidationError, match="timezone"):
        make_webhook(event_timestamp=datetime.fromisoformat("2026-08-30T09:00:00"))


@pytest.mark.parametrize(
    "reason",
    (
        "invalid provider signature",
        "payload checksum mismatch",
        "tenant does not match configured connector",
        "missing provider event identity",
        "incomplete provider payload",
    ),
)
def test_authenticity_checksum_tenant_and_schema_failures_are_quarantinable(
    reason: str,
) -> None:
    request = make_webhook()
    response = WebhookProcessingResponse(
        tenant_id=request.tenant_id,
        correlation_id=request.correlation_id,
        status=IntakeStatus.QUARANTINED,
        connector_id=request.connector_id,
        reason=reason,
        audit_reference="audit-webhook-1",
    )

    assert response.status is IntakeStatus.QUARANTINED
    assert response.reason == reason
    assert response.audit_reference == "audit-webhook-1"
    assert response.provider_event_id is None


def test_valid_duplicate_delivery_acknowledges_without_new_case_identity() -> None:
    response = WebhookProcessingResponse(
        tenant_id="tenant-a",
        correlation_id="corr-webhook-1",
        status=IntakeStatus.DUPLICATE,
        connector_id="razorpay-test",
        provider_event_id="evt_1",
        authoritative_mapping_id="mapping-1",
        incident_id="incident-1",
        case_id="case-1",
        association_status="resolved",
        verified_provider_correlation=verified_correlation(),
    )

    assert response.status is IntakeStatus.DUPLICATE
    assert response.provider_event_id == "evt_1"
    assert response.authoritative_mapping_id == "mapping-1"
    assert response.incident_id == "incident-1"
    assert response.case_id == "case-1"


def test_accepted_webhook_requires_provider_event_identity() -> None:
    with pytest.raises(ValidationError, match="provider_event_id"):
        WebhookProcessingResponse(
            tenant_id="tenant-a",
            correlation_id="corr-webhook-1",
            status=IntakeStatus.ACCEPTED,
            connector_id="razorpay-test",
        )


def test_accepted_webhook_requires_authoritative_mapping_and_mapped_case() -> None:
    with pytest.raises(ValidationError, match="authoritative_mapping_id"):
        WebhookProcessingResponse(
            tenant_id="tenant-a",
            correlation_id="corr-webhook-1",
            status=IntakeStatus.ACCEPTED,
            connector_id="razorpay-test",
            provider_event_id="evt_1",
            verified_provider_correlation=verified_correlation(),
        )


def test_verified_provider_correlation_is_strict_and_retains_verification_provenance() -> (
    None
):
    correlation = VerifiedProviderCorrelation(
        provider="razorpay",
        connector_id="razorpay-test",
        provider_event_id="evt_1",
        provider_payment_id="pay_1",
        provider_order_id="order_1",
        merchant_reference="merchant-ref-1",
        verification=VerifiedProviderVerification(
            state="verified",
            method="hmac-sha256-original-payload",
            provenance="secret/data/tenants/tenant-a/connectors/razorpay-test/webhook",
            payload_checksum="sha256:payload",
            verifier_version="razorpay-webhook-verifier@2.0.0",
            verified_at=datetime(2026, 8, 30, tzinfo=UTC),
        ),
    )
    assert correlation.correlation_schema_version == "1.0.0"
    assert correlation.verification.payload_checksum == "sha256:payload"
    with pytest.raises(ValidationError, match="extra"):
        VerifiedProviderCorrelation(
            **correlation.model_dump(),
            caller_case_id="case-1",
        )


def test_webhook_schema_is_strict_against_untrusted_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        make_webhook(execute_refund=True)
