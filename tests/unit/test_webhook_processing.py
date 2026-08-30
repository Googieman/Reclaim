"""Durable webhook processing and identity-isolation tests."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Self

import pytest
from app.auth.oidc import AuthenticatedPrincipal, IdentityType
from app.db.repositories.webhooks import WebhookDelivery, WebhookQuarantine
from app.intake.webhook_processing import (
    WebhookAssociationError,
    WebhookProcessingService,
)
from connectors.razorpay.webhook import RazorpayWebhookVerifier, payload_checksum

from packages.contracts.events import EventEnvelope
from packages.contracts.intake import IntakeStatus, RazorpayWebhookRequest

PAYLOAD = json.dumps(
    {"entity": "event", "id": "evt-1", "type": "payment.captured"},
    separators=(",", ":"),
).encode()
SECRET = "test-only-webhook-secret"


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
        "event_timestamp": datetime(2026, 8, 30, 9, tzinfo=UTC),
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


class MemoryWebhookRepository:
    def __init__(self) -> None:
        self.deliveries: dict[tuple[str, str], WebhookDelivery] = {}
        self.quarantines: list[WebhookQuarantine] = []

    def create_or_get(self, **values: object) -> Any:
        key = (str(values["connector_id"]), str(values["provider_event_id"]))
        existing = self.deliveries.get(key)
        if existing is not None:
            return type("Result", (), {"row": existing, "inserted": False})()
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
            incident_id=None
            if values["incident_id"] is None
            else str(values["incident_id"]),
            case_id=None if values["case_id"] is None else str(values["case_id"]),
            quarantine_reason=None,
            created_at=values["received_at"],
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
        )
        self.quarantines.append(row)
        return row


class MemoryCaseRepository:
    def __init__(self) -> None:
        self.rows = {
            "case-1": ("tenant-a", "case-1", "incident-1"),
            "case-2": ("tenant-a", "case-2", "incident-2"),
        }

    def get(self, *, case_id: str) -> tuple[str, str, str] | None:
        return self.rows.get(case_id)

    def find_by_incident_id(self, *, incident_id: str) -> tuple[str, str, str] | None:
        return next(
            (row for row in self.rows.values() if row[2] == incident_id),
            None,
        )


class MemoryIncidentRepository:
    def get(self, *, incident_id: str) -> tuple[str, str] | None:
        if incident_id in {"incident-1", "incident-2"}:
            return ("tenant-a", incident_id)
        return None


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
        audit: MemoryAudit,
        outbox: MemoryOutbox,
    ) -> None:
        self.webhooks = webhooks
        self.cases = MemoryCaseRepository()
        self.incidents = MemoryIncidentRepository()
        self.audit = audit
        self.outbox = outbox

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


def service() -> (
    tuple[
        WebhookProcessingService,
        MemoryWebhookRepository,
        MemoryRawStore,
        MemoryAudit,
        MemoryOutbox,
    ]
):
    webhooks = MemoryWebhookRepository()
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
        unit_of_work_factory=lambda _: MemoryUnitOfWork(webhooks, audit, outbox),
        raw_payload_store=raw_store,
        id_factory=ids,
    )
    return processor, webhooks, raw_store, audit, outbox


def test_valid_delivery_persists_raw_reference_and_audit_without_action_identity() -> (
    None
):
    processor, webhooks, raw_store, audit, outbox = service()

    result = processor.process(
        request(), authorization_context=context(), case_id="case-1"
    )

    assert result.status is IntakeStatus.ACCEPTED
    assert len(webhooks.deliveries) == 1
    delivery = next(iter(webhooks.deliveries.values()))
    assert delivery.original_payload == PAYLOAD
    assert delivery.raw_object_uri in raw_store.objects
    assert delivery.case_id == "case-1"
    assert len(audit.records) == 1
    assert audit.records[0].evidence_references == (delivery.raw_object_uri,)
    assert "idempotency" not in audit.records[0].action
    assert outbox.events == []


def test_valid_duplicate_acknowledges_without_second_delivery_record() -> None:
    processor, webhooks, _, audit, _ = service()

    first = processor.process(request(), authorization_context=context())
    duplicate = processor.process(request(), authorization_context=context())

    assert first.status is IntakeStatus.ACCEPTED
    assert duplicate.status is IntakeStatus.DUPLICATE
    assert duplicate.provider_event_id == first.provider_event_id
    assert len(webhooks.deliveries) == 1
    assert len(audit.records) == 2


def test_case_only_association_is_resolved_from_the_authoritative_mapping() -> None:
    processor, webhooks, _, _, _ = service()

    result = processor.process(
        request(),
        authorization_context=context(),
        case_id="case-1",
    )

    assert result.incident_id == "incident-1"
    assert result.case_id == "case-1"
    assert next(iter(webhooks.deliveries.values())).incident_id == "incident-1"


def test_mismatched_same_tenant_case_and_incident_are_rejected_before_persistence() -> None:
    processor, webhooks, raw_store, audit, _ = service()

    with pytest.raises(WebhookAssociationError, match="does not belong"):
        processor.process(
            request(),
            authorization_context=context(),
            incident_id="incident-2",
            case_id="case-1",
        )

    assert webhooks.deliveries == {}
    assert audit.records == []
    assert raw_store.objects == {}


def test_incomplete_delivery_is_quarantined_without_hash_identity_fallback() -> None:
    processor, webhooks, _, audit, outbox = service()

    result = processor.process(
        request(provider_event_id=None),
        authorization_context=context(),
    )

    assert result.status is IntakeStatus.QUARANTINED
    assert result.provider_event_id is None
    assert len(webhooks.deliveries) == 0
    assert len(webhooks.quarantines) == 1
    assert webhooks.quarantines[0].provider_event_id is None
    assert len(audit.records) == 1
    assert len(outbox.events) == 1
    assert outbox.events[0].event_type is not None
    assert outbox.events[0].payload["provider_event_id"] is None


def test_wrong_authenticated_tenant_is_rejected_before_raw_storage_or_database() -> (
    None
):
    processor, webhooks, raw_store, _, _ = service()

    with pytest.raises(PermissionError, match="configured tenant"):
        processor.process(request(), authorization_context=context("tenant-b"))

    assert webhooks.deliveries == {}
    assert webhooks.quarantines == []
    assert raw_store.objects == {}
