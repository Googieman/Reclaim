"""Implementation tests for the tenant-bound Razorpay webhook verifier."""

from datetime import UTC, datetime
import hashlib
import hmac
import json

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from connectors.razorpay.webhook import RazorpayWebhookVerifier, payload_checksum
from packages.contracts.intake import IntakeStatus, RazorpayWebhookRequest


PAYLOAD = json.dumps(
    {
        "entity": "event",
        "id": "evt-1",
        "type": "payment.captured",
        "created_at": 1788080400,
    },
    separators=(",", ":"),
).encode()
SECRET = "test-only-webhook-secret"


def context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="intake-api-test",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"service"})},
        identity_type=IdentityType.SERVICE,
        issuer="test-issuer",
    )
    return principal.for_tenant(tenant_id)


def request(**overrides: object) -> RazorpayWebhookRequest:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "correlation_id": "corr-webhook-1",
        "connector_id": "razorpay-test",
        "original_payload": PAYLOAD,
        "payload_checksum": payload_checksum(PAYLOAD),
        "signature": hmac.new(SECRET.encode(), PAYLOAD, hashlib.sha256).hexdigest(),
        "provider_event_id": "evt-1",
        "event_type": "payment.captured",
        "event_timestamp": datetime(2026, 8, 30, 9, tzinfo=UTC),
        "received_at": datetime(2026, 8, 30, 9, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return RazorpayWebhookRequest(**values)


def verifier(*, tenant_id: str = "tenant-a") -> RazorpayWebhookVerifier:
    return RazorpayWebhookVerifier(
        configured_tenant_id=tenant_id,
        connector_id="razorpay-test",
        secret_resolver=lambda **_: SECRET,
    )


def test_valid_original_payload_is_authenticated_and_preserved() -> None:
    result = verifier().verify(request(), authorization_context=context())

    assert result.status is IntakeStatus.ACCEPTED
    assert result.original_payload == PAYLOAD
    assert result.payload_checksum == payload_checksum(PAYLOAD)
    assert result.provider_event_id == "evt-1"


@pytest.mark.parametrize(
    "overrides",
    (
        {"signature": "bad"},
        {"payload_checksum": "sha256:wrong"},
        {"provider_event_id": None},
        {"event_type": None},
        {"event_timestamp": None},
    ),
)
def test_authenticity_identity_and_completeness_failures_quarantine(
    overrides: dict[str, object],
) -> None:
    result = verifier().verify(request(**overrides), authorization_context=context())

    assert result.status is IntakeStatus.QUARANTINED
    assert result.reason


def test_request_and_payload_tenant_mismatch_cannot_be_authority() -> None:
    result = verifier().verify(
        request(tenant_id="tenant-b"), authorization_context=context()
    )

    assert result.status is IntakeStatus.QUARANTINED
    assert result.reason == "tenant does not match configured connector"


def test_payload_identity_conflict_is_quarantined() -> None:
    payload = json.dumps(
        {"entity": "event", "id": "evt-other", "type": "payment.captured"},
        separators=(",", ":"),
    ).encode()
    result = verifier().verify(
        request(original_payload=payload, payload_checksum=payload_checksum(payload)),
        authorization_context=context(),
    )

    assert result.status is IntakeStatus.QUARANTINED
    assert result.reason == "provider event identity does not match payload"


def test_secret_reference_is_fixed_to_configured_tenant() -> None:
    captured: dict[str, object] = {}

    def resolver(**values: object) -> str:
        captured.update(values)
        return SECRET

    custom = RazorpayWebhookVerifier(
        configured_tenant_id="tenant-a",
        connector_id="razorpay-test",
        secret_resolver=resolver,
    )
    custom.verify(request(), authorization_context=context())

    assert captured["tenant_id"] == "tenant-a"
    assert captured["reference"] == (
        "secret/data/tenants/tenant-a/connectors/razorpay-test/webhook"
    )


def test_http_boundary_extracts_configured_headers_and_provider_metadata() -> None:
    signature = hmac.new(SECRET.encode(), PAYLOAD, hashlib.sha256).hexdigest()

    result = verifier().verify_http(
        correlation_id="corr-http-1",
        original_payload=PAYLOAD,
        headers={
            "x-razorpay-signature": signature,
            "x-razorpay-event-id": "evt-1",
        },
        received_at=datetime(2026, 8, 30, 9, 1, tzinfo=UTC),
        authorization_context=context(),
    )

    assert result.status is IntakeStatus.ACCEPTED
    assert result.provider_event_id == "evt-1"
    assert result.event_type == "payment.captured"
