"""D3 authoritative provider-correlation processing tests."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Self

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.db.repositories.provider_correlations import (
    ProviderCorrelationMapping,
    ProviderCorrelationResolution,
)
from app.db.repositories.webhooks import WebhookDelivery, WebhookQuarantine
from app.intake.webhook_processing import WebhookProcessingService
from connectors.razorpay.webhook import RazorpayWebhookVerifier, payload_checksum

from packages.contracts.events import EventEnvelope
from packages.contracts.intake import IntakeStatus, RazorpayWebhookRequest

PAYLOAD = json.dumps(
    {
        "entity": "event",
        "id": "evt-1",
        "type": "payment.captured",
        "created_at": 1788080400,
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay-1",
                    "order_id": "order-1",
                    "notes": {"merchant_reference": "merchant-ref-1"},
                }
            }
        },
    },
    separators=(",", ":"),
).encode()
SECRET = "test-only-webhook-secret"
NOW = datetime(2026, 8, 30, 9, tzinfo=UTC)


def context(tenant_id: str = "tenant-a"):
    principal = AuthenticatedPrincipal(
        subject="reviewer-1",
        tenant_ids=frozenset({tenant_id}),
        tenant_roles={tenant_id: frozenset({"reviewer"})},
        identity_type=IdentityType.USER,
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
        "event_timestamp": NOW,
        "received_at": datetime(2026, 8, 30, 9, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return RazorpayWebhookRequest(**values)


@dataclass
class StoredObject:
    object_name: str


class MemoryRawStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, **values: object) -> StoredObject:
        name = str(values["object_name"])
        content = bytes(values["content"])
        assert values["tenant_id"] == "tenant-a"
        assert values["expected_checksum"] == payload_checksum(content)
        self.objects[name] = content
        return StoredObject(name)


def mapping() -> ProviderCorrelationMapping:
    return ProviderCorrelationMapping(
        tenant_id="tenant-a",
        mapping_id="mapping-1",
        correlation_schema_version="1.0.0",
        provider="razorpay",
        connector_id="razorpay-test",
        provider_event_id=None,
        provider_payment_id="pay-1",
        provider_order_id="order-1",
        merchant_reference="merchant-ref-1",
        incident_id="incident-1",
        case_id="case-1",
        related_order_reference="merchant://orders/order-1",
        related_payment_reference="merchant://payments/pay-1",
        mapping_source="merchant_order_payment_context",
        mapping_source_reference="merchant://orders/order-1",
        mapping_source_checksum="sha256:trusted-mapping",
        mapping_status="active",
        created_at=datetime(2026, 8, 30, 8, tzinfo=UTC),
        verified_at=datetime(2026, 8, 30, 8, tzinfo=UTC),
        revoked_at=None,
    )


class MemoryWebhookRepository:
    def __init__(self) -> None:
        self.deliveries: dict[tuple[str, str], WebhookDelivery] = {}
        self.quarantines: list[WebhookQuarantine] = []

    def get(
        self, *, connector_id: str, provider_event_id: str
    ) -> WebhookDelivery | None:
        return self.deliveries.get((connector_id, provider_event_id))

    def create_or_get(self, **values: object) -> Any:
        key = (str(values["connector_id"]), str(values["provider_event_id"]))
        existing = self.deliveries.get(key)
        if existing is not None:
            return type("Result", (), {"row": existing, "inserted": False})()
        trusted_mapping = values["mapping"]
        correlation = values["verified_provider_correlation"]
        assert isinstance(trusted_mapping, ProviderCorrelationMapping)
        row = WebhookDelivery(
            tenant_id="tenant-a",
            connector_id=key[0],
            provider_event_id=key[1],
            original_payload=bytes(values["original_payload"]),
            payload_checksum=str(values["payload_checksum"]),
            raw_object_uri=str(values["raw_object_uri"]),
            signature=str(values["signature"]),
            event_type=str(values["event_type"]),
            event_timestamp=values["event_timestamp"],
            received_at=values["received_at"],
            processing_status="accepted",
            incident_id=trusted_mapping.incident_id,
            case_id=trusted_mapping.case_id,
            quarantine_reason=None,
            created_at=values["received_at"],
            authoritative_mapping_id=trusted_mapping.mapping_id,
            related_order_reference=trusted_mapping.related_order_reference,
            related_payment_reference=trusted_mapping.related_payment_reference,
            verified_provider_correlation=correlation,
            asserted_tenant_id=str(values["asserted_tenant_id"]),
            asserted_merchant_id=values.get("asserted_merchant_id"),
            asserted_incident_id=values.get("asserted_incident_id"),
            asserted_case_id=values.get("asserted_case_id"),
            assertion_status=str(values["assertion_status"]),
        )
        self.deliveries[key] = row
        return type("Result", (), {"row": row, "inserted": True})()

    def quarantine(self, **values: object) -> WebhookQuarantine:
        row = WebhookQuarantine(
            tenant_id="tenant-a",
            quarantine_id=str(values["quarantine_id"]),
            connector_id=str(values["connector_id"]),
            provider_event_id=values["provider_event_id"],
            original_payload=bytes(values["original_payload"]),
            payload_checksum=str(values["payload_checksum"]),
            raw_object_uri=str(values["raw_object_uri"]),
            signature=values["signature"],
            event_type=values["event_type"],
            event_timestamp=values["event_timestamp"],
            received_at=values["received_at"],
            quarantine_reason=str(values["reason"]),
            created_at=values["received_at"],
            verified_provider_correlation=values.get("verified_provider_correlation"),
            association_status=values.get("association_status"),
            asserted_tenant_id=values.get("asserted_tenant_id"),
            asserted_merchant_id=values.get("asserted_merchant_id"),
            asserted_incident_id=values.get("asserted_incident_id"),
            asserted_case_id=values.get("asserted_case_id"),
        )
        self.quarantines.append(row)
        return row


class MemoryProviderCorrelationRepository:
    def __init__(self, trusted_mapping: ProviderCorrelationMapping | None) -> None:
        self.trusted_mapping = trusted_mapping
        self.register_calls = 0

    def resolve(self, correlation: object) -> ProviderCorrelationResolution:
        if self.trusted_mapping is None:
            return ProviderCorrelationResolution(None, "unresolved_association")
        mapping_value = self.trusted_mapping
        assert hasattr(correlation, "provider_payment_id")
        if (
            correlation.provider_payment_id != mapping_value.provider_payment_id
            or correlation.provider_order_id != mapping_value.provider_order_id
            or correlation.merchant_reference != mapping_value.merchant_reference
        ):
            return ProviderCorrelationResolution(None, "mapping_conflict")
        return ProviderCorrelationResolution(mapping_value)

    def register(self, **_: object) -> None:
        self.register_calls += 1
        raise AssertionError("webhook processing must never create a provider mapping")


class MemoryAudit:
    def __init__(self) -> None:
        self.records: list[Any] = []

    def latest_checksum(self, *, tenant_id: str) -> str | None:
        records = [record for record in self.records if record.tenant_id == tenant_id]
        return None if not records else records[-1].record_checksum

    def append(self, record: Any) -> Any:
        self.records.append(record)
        return record


class MemoryOutbox:
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    def enqueue(self, *, outbox_id: str, event: EventEnvelope) -> EventEnvelope:
        self.events.append(event)
        return event


class MemoryUnitOfWork:
    def __init__(
        self,
        webhooks: MemoryWebhookRepository,
        provider_correlations: MemoryProviderCorrelationRepository,
        audit: MemoryAudit,
        outbox: MemoryOutbox,
    ) -> None:
        self.webhooks = webhooks
        self.provider_correlations = provider_correlations
        self.audit = audit
        self.outbox = outbox

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


def service(
    trusted_mapping: ProviderCorrelationMapping | None = None,
) -> tuple[
    WebhookProcessingService,
    MemoryWebhookRepository,
    MemoryRawStore,
    MemoryAudit,
    MemoryOutbox,
    MemoryProviderCorrelationRepository,
]:
    webhooks = MemoryWebhookRepository()
    mappings = MemoryProviderCorrelationRepository(trusted_mapping)
    raw_store = MemoryRawStore()
    audit = MemoryAudit()
    outbox = MemoryOutbox()
    counters: dict[str, int] = {}

    def ids(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    processor = WebhookProcessingService(
        verifier=RazorpayWebhookVerifier(
            configured_tenant_id="tenant-a",
            connector_id="razorpay-test",
            secret_resolver=lambda **_: SECRET,
        ),
        unit_of_work_factory=lambda _: MemoryUnitOfWork(
            webhooks, mappings, audit, outbox
        ),
        raw_payload_store=raw_store,
        id_factory=ids,
    )
    return processor, webhooks, raw_store, audit, outbox, mappings


def test_valid_mapped_delivery_persists_verified_correlation_and_mapping() -> None:
    processor, webhooks, raw_store, audit, outbox, _ = service(mapping())

    result = processor.process(request(), authorization_context=context())

    assert result.status is IntakeStatus.ACCEPTED
    assert result.authoritative_mapping_id == "mapping-1"
    assert (result.incident_id, result.case_id) == ("incident-1", "case-1")
    delivery = next(iter(webhooks.deliveries.values()))
    assert delivery.verified_provider_correlation is not None
    assert delivery.verified_provider_correlation.provider_payment_id == "pay-1"
    assert delivery.raw_object_uri in raw_store.objects
    assert audit.records[0].input_references
    assert "mapping:mapping-1" in audit.records[0].input_references
    assert outbox.events == []


def test_same_tenant_arbitrary_case_without_mapping_is_quarantined() -> None:
    processor, webhooks, raw_store, audit, outbox, mappings = service()

    result = processor.process(
        request(), authorization_context=context(), case_id="case-1"
    )

    assert result.status is IntakeStatus.QUARANTINED
    assert result.reason == "unresolved_association"
    assert result.case_id is None
    assert webhooks.deliveries == {}
    assert webhooks.quarantines[0].asserted_case_id == "case-1"
    assert webhooks.quarantines[0].verified_provider_correlation is not None
    assert len(audit.records) == 1
    assert len(outbox.events) == 1
    assert mappings.register_calls == 0


def test_mapping_resolves_without_caller_ids_and_matching_assertions_are_accepted() -> (
    None
):
    processor, _, _, _, _, _ = service(mapping())

    without_assertion = processor.process(request(), authorization_context=context())
    assert without_assertion.status is IntakeStatus.ACCEPTED
    assert without_assertion.case_id == "case-1"

    processor, _, _, _, _, _ = service(mapping())
    with_matching_assertion = processor.process(
        request(),
        authorization_context=context(),
        incident_id="incident-1",
        case_id="case-1",
    )
    assert with_matching_assertion.status is IntakeStatus.ACCEPTED
    assert with_matching_assertion.association_status == "resolved"


@pytest.mark.parametrize(
    ("incident_id", "case_id"),
    ((None, "case-2"), ("incident-2", None), ("incident-2", "case-2")),
)
def test_conflicting_case_or_incident_assertions_quarantine_without_attachment(
    incident_id: str | None, case_id: str | None
) -> None:
    processor, webhooks, _, _, _, _ = service(mapping())

    result = processor.process(
        request(),
        authorization_context=context(),
        incident_id=incident_id,
        case_id=case_id,
    )

    assert result.status is IntakeStatus.QUARANTINED
    assert result.reason == "assertion_mismatch"
    assert result.incident_id is None and result.case_id is None
    assert webhooks.deliveries == {}
    assert webhooks.quarantines[0].association_status == "assertion_mismatch"


def test_duplicate_provider_event_returns_existing_authoritative_outcome() -> None:
    processor, webhooks, _, audit, outbox, _ = service(mapping())

    first = processor.process(request(), authorization_context=context())
    duplicate = processor.process(
        request(), authorization_context=context(), case_id="case-1"
    )

    assert first.status is IntakeStatus.ACCEPTED
    assert duplicate.status is IntakeStatus.DUPLICATE
    assert duplicate.authoritative_mapping_id == "mapping-1"
    assert (duplicate.incident_id, duplicate.case_id) == ("incident-1", "case-1")
    assert len(webhooks.deliveries) == 1
    assert len(audit.records) == 2
    assert outbox.events == []


def test_provider_event_reuse_with_different_bytes_quarantines() -> None:
    processor, webhooks, _, _, _, _ = service(mapping())
    processor.process(request(), authorization_context=context())

    different_payload = PAYLOAD.replace(b"pay-1", b"pay-2")
    result = processor.process(
        request(
            original_payload=different_payload,
            payload_checksum=payload_checksum(different_payload),
            signature=hmac.new(
                SECRET.encode(), different_payload, hashlib.sha256
            ).hexdigest(),
        ),
        authorization_context=context(),
    )

    assert result.status is IntakeStatus.QUARANTINED
    assert result.reason == "provider_identity_conflict"
    assert len(webhooks.deliveries) == 1
    assert len(webhooks.quarantines) == 1


def test_unverified_correlation_is_not_accepted_and_is_quarantined() -> None:
    processor, webhooks, _, _, outbox, _ = service(mapping())

    result = processor.process(
        request(original_payload=PAYLOAD.replace(b"pay-1", b"")),
        authorization_context=context(),
    )

    assert result.status is IntakeStatus.QUARANTINED
    assert result.verified_provider_correlation is None
    assert webhooks.deliveries == {}
    assert len(outbox.events) == 1


def test_wrong_authenticated_tenant_is_rejected_before_raw_storage_or_database() -> (
    None
):
    processor, webhooks, raw_store, _, _, _ = service(mapping())

    with pytest.raises(PermissionError, match="configured tenant"):
        processor.process(request(), authorization_context=context("tenant-b"))

    assert webhooks.deliveries == {}
    assert webhooks.quarantines == []
    assert raw_store.objects == {}
