"""Durable Razorpay webhook processing after original-payload verification."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from connectors.razorpay.webhook import RazorpayWebhookVerifier, WebhookVerification
from packages.contracts.events import EventEnvelope, EventType
from packages.contracts.intake import (
    IntakeStatus,
    RazorpayWebhookRequest,
    WebhookProcessingResponse,
)

from app.audit.intake import append_webhook_audit
from app.auth.oidc import RequiredRole, TenantAuthorizationContext, TenantAuthorizationError
from app.db.unit_of_work import PostgresUnitOfWork


class RawPayloadObject(Protocol):
    object_name: str


class RawPayloadStore(Protocol):
    def put(
        self,
        *,
        tenant_id: str,
        object_name: str,
        content: bytes,
        content_type: str,
        expected_checksum: str,
    ) -> RawPayloadObject: ...


UnitOfWorkFactory = Callable[[TenantAuthorizationContext], PostgresUnitOfWork]
IdFactory = Callable[[str], str]


class WebhookProcessingError(RuntimeError):
    """Raised when a verified delivery cannot be durably recorded."""


class WebhookProcessingService:
    """Persist webhook evidence and outcomes in one tenant-scoped transaction.

    Provider identity is the only webhook deduplication key.  No action identity
    or payload hash is used as a substitute for a missing provider ID.
    """

    def __init__(
        self,
        *,
        verifier: RazorpayWebhookVerifier,
        unit_of_work_factory: UnitOfWorkFactory,
        raw_payload_store: RawPayloadStore,
        id_factory: IdFactory,
        actor: str = "razorpay-webhook@1.0.0",
    ) -> None:
        if not actor.strip():
            raise ValueError("webhook processor actor is required")
        self.verifier = verifier
        self.unit_of_work_factory = unit_of_work_factory
        self.raw_payload_store = raw_payload_store
        self.id_factory = id_factory
        self.actor = actor

    def process(
        self,
        request: RazorpayWebhookRequest,
        *,
        authorization_context: TenantAuthorizationContext,
        incident_id: str | None = None,
        case_id: str | None = None,
    ) -> WebhookProcessingResponse:
        _require_webhook_authority(authorization_context, self.verifier.configured_tenant_id)
        verification = self.verifier.verify(
            request,
            authorization_context=authorization_context,
        )
        raw_object_uri = self._store_raw_payload(verification)
        recorded_at = request.received_at

        if verification.status is IntakeStatus.QUARANTINED:
            quarantine_id = self.id_factory("quarantine")
            with self.unit_of_work_factory(authorization_context) as unit_of_work:
                quarantine = unit_of_work.webhooks.quarantine(
                    quarantine_id=quarantine_id,
                    connector_id=verification.connector_id,
                    provider_event_id=verification.provider_event_id,
                    original_payload=verification.original_payload,
                    payload_checksum=verification.payload_checksum,
                    raw_object_uri=raw_object_uri,
                    signature=request.signature,
                    event_type=verification.event_type,
                    event_timestamp=verification.event_timestamp,
                    received_at=recorded_at,
                    reason=verification.reason or "webhook verification failed",
                )
                audit = append_webhook_audit(
                    unit_of_work=unit_of_work,
                    audit_id=self.id_factory("audit"),
                    tenant_id=authorization_context.tenant_id,
                    correlation_id=request.correlation_id,
                    actor=self.actor,
                    outcome=IntakeStatus.QUARANTINED.value,
                    recorded_at=recorded_at,
                    raw_object_reference=raw_object_uri,
                    provider_event_id=verification.provider_event_id,
                    connector_id=verification.connector_id,
                    output_references=(quarantine.quarantine_id,),
                    reason=verification.reason,
                )
                unit_of_work.outbox.enqueue(
                    outbox_id=self.id_factory("outbox"),
                    event=_quarantine_event(
                        verification=verification,
                        quarantine_id=quarantine.quarantine_id,
                        recorded_at=recorded_at,
                        producer=self.actor,
                    ),
                )
            return WebhookProcessingResponse(
                tenant_id=authorization_context.tenant_id,
                correlation_id=request.correlation_id,
                status=IntakeStatus.QUARANTINED,
                connector_id=verification.connector_id,
                provider_event_id=verification.provider_event_id,
                reason=verification.reason,
                audit_reference=audit.audit_id,
            )

        if verification.provider_event_id is None:
            raise WebhookProcessingError("accepted webhook has no provider event identity")
        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            result = unit_of_work.webhooks.create_or_get(
                connector_id=verification.connector_id,
                provider_event_id=verification.provider_event_id,
                original_payload=verification.original_payload,
                payload_checksum=verification.payload_checksum,
                raw_object_uri=raw_object_uri,
                signature=request.signature,
                event_type=verification.event_type,
                event_timestamp=verification.event_timestamp,
                received_at=recorded_at,
                incident_id=incident_id,
                case_id=case_id,
            )
            outcome = IntakeStatus.ACCEPTED if result.inserted else IntakeStatus.DUPLICATE
            audit = append_webhook_audit(
                unit_of_work=unit_of_work,
                audit_id=self.id_factory("audit"),
                tenant_id=authorization_context.tenant_id,
                correlation_id=request.correlation_id,
                actor=self.actor,
                outcome=outcome.value,
                recorded_at=recorded_at,
                raw_object_reference=raw_object_uri,
                provider_event_id=verification.provider_event_id,
                connector_id=verification.connector_id,
                case_id=result.row.case_id,
                output_references=tuple(
                    reference
                    for reference in (result.row.incident_id, result.row.case_id)
                    if reference
                ),
            )

        return WebhookProcessingResponse(
            tenant_id=authorization_context.tenant_id,
            correlation_id=request.correlation_id,
            status=outcome,
            connector_id=verification.connector_id,
            provider_event_id=verification.provider_event_id,
            incident_id=result.row.incident_id,
            case_id=result.row.case_id,
            audit_reference=audit.audit_id,
        )

    def _store_raw_payload(self, verification: WebhookVerification) -> str:
        identity = verification.provider_event_id or self.id_factory("quarantine-object")
        safe_identity = identity if _is_safe_object_segment(identity) else _hex_identity(identity)
        stored = self.raw_payload_store.put(
            tenant_id=self.verifier.configured_tenant_id,
            object_name=f"webhooks/{verification.connector_id}/{safe_identity}.json",
            content=verification.original_payload,
            content_type="application/json",
            expected_checksum=verification.payload_checksum,
        )
        return stored.object_name


def _require_webhook_authority(
    authorization_context: TenantAuthorizationContext, configured_tenant_id: str
) -> None:
    if authorization_context.tenant_id != configured_tenant_id:
        raise TenantAuthorizationError(
            "webhook processor authority is not scoped to configured tenant"
        )
    authorization_context.require_role(RequiredRole.REVIEWER)


def _quarantine_event(
    *,
    verification: WebhookVerification,
    quarantine_id: str,
    recorded_at: datetime,
    producer: str,
) -> EventEnvelope:
    payload: dict[str, Any] = {
        "connector_id": verification.connector_id,
        "quarantine_id": quarantine_id,
        "provider_event_id": verification.provider_event_id,
        "payload_checksum": verification.payload_checksum,
        "reason": verification.reason,
    }
    return EventEnvelope(
        tenant_id=verification.tenant_id,
        correlation_id=verification.correlation_id,
        event_id=f"webhook.quarantined:{quarantine_id}",
        event_type=EventType.WEBHOOK_QUARANTINED,
        aggregate_type="webhook",
        aggregate_id=quarantine_id,
        occurred_at=recorded_at,
        produced_at=recorded_at,
        causation_id=f"webhook:{verification.correlation_id}",
        producer=producer,
        payload_checksum=_event_payload_checksum(payload),
        payload=payload,
    )


def _event_payload_checksum(payload: dict[str, Any]) -> str:
    import hashlib
    import json

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_safe_object_segment(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "._-" for character in value)


def _hex_identity(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
