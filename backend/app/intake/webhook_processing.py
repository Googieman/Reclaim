"""Durable Razorpay webhook processing after original-payload verification."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from connectors.razorpay.webhook import RazorpayWebhookVerifier, WebhookVerification
from packages.contracts.intake import (
    IntakeStatus,
    RazorpayWebhookRequest,
    WebhookProcessingResponse,
)

from app.audit.intake import append_webhook_audit
from app.auth.oidc import RequiredRole, TenantAuthorizationContext, TenantAuthorizationError
from app.db.unit_of_work import PostgresUnitOfWork
from app.events.incident_events import build_webhook_quarantined_event


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


class WebhookAssociationError(WebhookProcessingError):
    """Raised when caller-supplied case and incident identities do not agree."""


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
        recorded_at = request.received_at

        # Oversized input is rejected at the trust boundary.  In particular it
        # must not be persisted as quarantine evidence or emit a quarantine
        # event, because those are downstream side effects of accepted-size
        # input only.
        if verification.payload_size_exceeded:
            return WebhookProcessingResponse(
                tenant_id=authorization_context.tenant_id,
                correlation_id=request.correlation_id,
                status=IntakeStatus.QUARANTINED,
                connector_id=verification.connector_id,
                provider_event_id=verification.provider_event_id,
                reason=verification.reason,
            )

        if verification.status is IntakeStatus.QUARANTINED:
            quarantine_id = self.id_factory("quarantine")
            raw_object_uri = self._store_raw_payload(verification)
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
                    event=build_webhook_quarantined_event(
                        tenant_id=verification.tenant_id,
                        correlation_id=verification.correlation_id,
                        quarantine_id=quarantine.quarantine_id,
                        connector_id=verification.connector_id,
                        provider_event_id=verification.provider_event_id,
                        raw_payload_checksum=verification.payload_checksum,
                        reason=verification.reason or "webhook verification failed",
                        recorded_at=recorded_at,
                        causation_id=f"webhook:{verification.correlation_id}",
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
            authoritative_incident_id, authoritative_case_id = _resolve_association(
                unit_of_work,
                incident_id=incident_id,
                case_id=case_id,
                tenant_id=authorization_context.tenant_id,
            )
            raw_object_uri = self._store_raw_payload(verification)
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
                incident_id=authoritative_incident_id,
                case_id=authoritative_case_id,
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


def _is_safe_object_segment(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in "._-" for character in value)


def _hex_identity(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _resolve_association(
    unit_of_work: PostgresUnitOfWork,
    *,
    incident_id: str | None,
    case_id: str | None,
    tenant_id: str,
) -> tuple[str | None, str | None]:
    """Resolve optional IDs from the authoritative tenant-scoped case mapping."""

    if incident_id is None and case_id is None:
        return None, None
    if incident_id is not None and not incident_id.strip():
        raise WebhookAssociationError("webhook incident association cannot be blank")
    if case_id is not None and not case_id.strip():
        raise WebhookAssociationError("webhook case association cannot be blank")
    if case_id is not None:
        case_row = unit_of_work.cases.get(case_id=case_id)
    else:
        case_row = unit_of_work.cases.find_by_incident_id(incident_id=incident_id or "")
    if case_row is None:
        raise WebhookAssociationError("webhook case/incident association is not authoritative")
    if str(case_row[0]) != tenant_id or (case_id is not None and str(case_row[1]) != case_id):
        raise WebhookAssociationError("webhook case association crosses tenant boundary")
    resolved_incident_id = str(case_row[2])
    resolved_case_id = str(case_row[1])
    if incident_id is not None and incident_id != resolved_incident_id:
        raise WebhookAssociationError("webhook incident does not belong to the supplied case")
    incidents = getattr(unit_of_work, "incidents", None)
    if incidents is not None:
        incident_row = incidents.get(incident_id=resolved_incident_id)
        if incident_row is None or str(incident_row[0]) != tenant_id:
            raise WebhookAssociationError("webhook incident is not authoritative for the case")
    return resolved_incident_id, resolved_case_id


__all__ = [
    "WebhookAssociationError",
    "WebhookProcessingError",
    "WebhookProcessingService",
]
