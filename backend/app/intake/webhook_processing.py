"""Durable Razorpay webhook processing after verified provider correlation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from connectors.razorpay.webhook import RazorpayWebhookVerifier, WebhookVerification
from packages.contracts.intake import (
    IntakeStatus,
    RazorpayWebhookRequest,
    VerifiedProviderCorrelation,
    WebhookProcessingResponse,
)

from app.audit.intake import append_webhook_audit
from app.auth.oidc import RequiredRole, TenantAuthorizationContext, TenantAuthorizationError
from app.db.repositories.webhooks import WebhookDelivery
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
    """Retained as a compatibility type for callers handling association failures."""


class WebhookProcessingService:
    """Persist only provider-authenticated, authoritatively mapped deliveries."""

    def __init__(
        self,
        *,
        verifier: RazorpayWebhookVerifier,
        unit_of_work_factory: UnitOfWorkFactory,
        raw_payload_store: RawPayloadStore,
        id_factory: IdFactory,
        actor: str = "razorpay-webhook@2.0.0",
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
        merchant_id: str | None = None,
    ) -> WebhookProcessingResponse:
        _require_webhook_authority(authorization_context, self.verifier.configured_tenant_id)
        verification = self.verifier.verify(
            request,
            authorization_context=authorization_context,
        )
        recorded_at = request.received_at

        # Oversized input is rejected at the trust boundary and is not persisted.
        if verification.payload_size_exceeded:
            return _response(
                tenant_id=authorization_context.tenant_id,
                correlation_id=request.correlation_id,
                status=IntakeStatus.QUARANTINED,
                verification=verification,
                reason=verification.reason,
                association_status="verification_failed",
            )

        if verification.status is IntakeStatus.QUARANTINED:
            with self.unit_of_work_factory(authorization_context) as unit_of_work:
                return self._quarantine(
                    unit_of_work=unit_of_work,
                    request=request,
                    verification=verification,
                    reason=verification.reason or "webhook verification failed",
                    association_status="verification_failed",
                    incident_id=incident_id,
                    case_id=case_id,
                    merchant_id=merchant_id or request.merchant_id,
                    recorded_at=recorded_at,
                )

        correlation = verification.verified_provider_correlation
        if correlation is None:
            raise WebhookProcessingError(
                "accepted webhook verification has no verified provider correlation"
            )

        with self.unit_of_work_factory(authorization_context) as unit_of_work:
            existing = unit_of_work.webhooks.get(
                connector_id=verification.connector_id,
                provider_event_id=correlation.provider_event_id,
            )
            if existing is not None:
                if not _same_delivery_identity(existing, verification, correlation):
                    return self._quarantine(
                        unit_of_work=unit_of_work,
                        request=request,
                        verification=verification,
                        reason="provider_identity_conflict",
                        association_status="mapping_conflict",
                        incident_id=incident_id,
                        case_id=case_id,
                        merchant_id=merchant_id or request.merchant_id,
                        recorded_at=recorded_at,
                    )
                assertion_status, assertion_reason = _check_assertions(
                    existing.incident_id,
                    existing.case_id,
                    authorization_context.tenant_id,
                    incident_id=incident_id,
                    case_id=case_id,
                )
                if assertion_reason:
                    return self._quarantine(
                        unit_of_work=unit_of_work,
                        request=request,
                        verification=verification,
                        reason=assertion_reason,
                        association_status="assertion_mismatch",
                        incident_id=incident_id,
                        case_id=case_id,
                        merchant_id=merchant_id or request.merchant_id,
                        recorded_at=recorded_at,
                    )
                audit = append_webhook_audit(
                    unit_of_work=unit_of_work,
                    audit_id=self.id_factory("audit"),
                    tenant_id=authorization_context.tenant_id,
                    correlation_id=request.correlation_id,
                    actor=self.actor,
                    outcome=IntakeStatus.DUPLICATE.value,
                    recorded_at=recorded_at,
                    raw_object_reference=existing.raw_object_uri or "persisted-webhook",
                    provider_event_id=correlation.provider_event_id,
                    connector_id=verification.connector_id,
                    case_id=existing.case_id,
                    authoritative_mapping_id=existing.authoritative_mapping_id,
                    verified_provider_correlation=correlation,
                    assertion_status=assertion_status,
                    asserted_incident_id=incident_id,
                    asserted_case_id=case_id,
                )
                return _response(
                    tenant_id=authorization_context.tenant_id,
                    correlation_id=request.correlation_id,
                    status=IntakeStatus.DUPLICATE,
                    verification=verification,
                    provider_event_id=correlation.provider_event_id,
                    incident_id=existing.incident_id,
                    case_id=existing.case_id,
                    authoritative_mapping_id=existing.authoritative_mapping_id,
                    association_status="resolved",
                    audit_reference=audit.audit_id,
                )

            resolution = unit_of_work.provider_correlations.resolve(correlation)
            if not resolution.resolved or resolution.mapping is None:
                return self._quarantine(
                    unit_of_work=unit_of_work,
                    request=request,
                    verification=verification,
                    reason=resolution.reason or "unresolved_association",
                    association_status=resolution.reason or "unresolved_association",
                    incident_id=incident_id,
                    case_id=case_id,
                    merchant_id=merchant_id or request.merchant_id,
                    recorded_at=recorded_at,
                )

            mapping = resolution.mapping
            assertion_status, assertion_reason = _check_assertions(
                mapping.incident_id,
                mapping.case_id,
                authorization_context.tenant_id,
                incident_id=incident_id,
                case_id=case_id,
            )
            if assertion_reason:
                return self._quarantine(
                    unit_of_work=unit_of_work,
                    request=request,
                    verification=verification,
                    reason=assertion_reason,
                    association_status="assertion_mismatch",
                    incident_id=incident_id,
                    case_id=case_id,
                    merchant_id=merchant_id or request.merchant_id,
                    recorded_at=recorded_at,
                )

            raw_object_uri = self._store_raw_payload(verification)
            result = unit_of_work.webhooks.create_or_get(
                mapping=mapping,
                verified_provider_correlation=correlation,
                connector_id=verification.connector_id,
                provider_event_id=correlation.provider_event_id,
                original_payload=verification.original_payload,
                payload_checksum=verification.payload_checksum,
                raw_object_uri=raw_object_uri,
                signature=request.signature,
                event_type=verification.event_type,
                event_timestamp=verification.event_timestamp,
                received_at=recorded_at,
                asserted_tenant_id=request.tenant_id,
                asserted_merchant_id=merchant_id or request.merchant_id,
                asserted_incident_id=incident_id,
                asserted_case_id=case_id,
                assertion_status=assertion_status,
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
                raw_object_reference=result.row.raw_object_uri or raw_object_uri,
                provider_event_id=correlation.provider_event_id,
                connector_id=verification.connector_id,
                case_id=result.row.case_id,
                authoritative_mapping_id=result.row.authoritative_mapping_id,
                verified_provider_correlation=correlation,
                assertion_status=assertion_status,
                asserted_incident_id=incident_id,
                asserted_case_id=case_id,
            )

        return _response(
            tenant_id=authorization_context.tenant_id,
            correlation_id=request.correlation_id,
            status=outcome,
            verification=verification,
            provider_event_id=correlation.provider_event_id,
            incident_id=result.row.incident_id,
            case_id=result.row.case_id,
            authoritative_mapping_id=result.row.authoritative_mapping_id,
            association_status="resolved",
            audit_reference=audit.audit_id,
        )

    def _quarantine(
        self,
        *,
        unit_of_work: PostgresUnitOfWork,
        request: RazorpayWebhookRequest,
        verification: WebhookVerification,
        reason: str,
        association_status: str,
        incident_id: str | None,
        case_id: str | None,
        merchant_id: str | None,
        recorded_at: object,
    ) -> WebhookProcessingResponse:
        if not isinstance(recorded_at, type(request.received_at)):
            raise WebhookProcessingError("webhook recorded timestamp is invalid")
        quarantine_id = self.id_factory("quarantine")
        raw_object_uri = self._store_raw_payload(verification, object_identity=quarantine_id)
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
            received_at=request.received_at,
            reason=reason,
            verified_provider_correlation=verification.verified_provider_correlation,
            association_status=association_status,
            asserted_tenant_id=request.tenant_id,
            asserted_merchant_id=merchant_id,
            asserted_incident_id=incident_id,
            asserted_case_id=case_id,
        )
        audit = append_webhook_audit(
            unit_of_work=unit_of_work,
            audit_id=self.id_factory("audit"),
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            actor=self.actor,
            outcome=IntakeStatus.QUARANTINED.value,
            recorded_at=request.received_at,
            raw_object_reference=raw_object_uri,
            provider_event_id=verification.provider_event_id,
            connector_id=verification.connector_id,
            authoritative_mapping_id=None,
            verified_provider_correlation=verification.verified_provider_correlation,
            assertion_status=association_status,
            asserted_incident_id=incident_id,
            asserted_case_id=case_id,
            output_references=(quarantine.quarantine_id,),
            reason=reason,
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
                reason=reason,
                recorded_at=request.received_at,
                causation_id=f"webhook:{verification.correlation_id}",
                producer=self.actor,
                verified_provider_correlation=verification.verified_provider_correlation,
                association_status=association_status,
            ),
        )
        return _response(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            status=IntakeStatus.QUARANTINED,
            verification=verification,
            provider_event_id=verification.provider_event_id,
            association_status=association_status,
            reason=reason,
            audit_reference=audit.audit_id,
        )

    def _store_raw_payload(
        self, verification: WebhookVerification, *, object_identity: str | None = None
    ) -> str:
        identity = (
            object_identity
            or verification.provider_event_id
            or self.id_factory("quarantine-object")
        )
        safe_identity = identity if _is_safe_object_segment(identity) else _hex_identity(identity)
        stored = self.raw_payload_store.put(
            tenant_id=self.verifier.configured_tenant_id,
            object_name=f"webhooks/{verification.connector_id}/{safe_identity}.json",
            content=verification.original_payload,
            content_type="application/json",
            expected_checksum=verification.payload_checksum,
        )
        return stored.object_name


def _response(
    *,
    tenant_id: str,
    correlation_id: str,
    status: IntakeStatus,
    verification: WebhookVerification,
    provider_event_id: str | None = None,
    incident_id: str | None = None,
    case_id: str | None = None,
    authoritative_mapping_id: str | None = None,
    association_status: str | None = None,
    reason: str | None = None,
    audit_reference: str | None = None,
) -> WebhookProcessingResponse:
    return WebhookProcessingResponse(
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        status=status,
        connector_id=verification.connector_id,
        provider_event_id=provider_event_id or verification.provider_event_id,
        incident_id=incident_id,
        case_id=case_id,
        authoritative_mapping_id=authoritative_mapping_id,
        association_status=association_status,
        verified_provider_correlation=verification.verified_provider_correlation,
        reason=reason,
        audit_reference=audit_reference,
    )


def _same_delivery_identity(
    existing: WebhookDelivery,
    verification: WebhookVerification,
    correlation: VerifiedProviderCorrelation,
) -> bool:
    return (
        existing.original_payload == verification.original_payload
        and existing.payload_checksum == verification.payload_checksum
        and existing.verified_provider_correlation == correlation
    )


def _check_assertions(
    authoritative_incident_id: str | None,
    authoritative_case_id: str | None,
    tenant_id: str,
    *,
    incident_id: str | None,
    case_id: str | None,
) -> tuple[str, str | None]:
    del tenant_id  # tenant scope is supplied by the authenticated UoW/RLS context.
    if incident_id is not None and not incident_id.strip():
        return "mismatch", "assertion_mismatch"
    if case_id is not None and not case_id.strip():
        return "mismatch", "assertion_mismatch"
    if incident_id is not None and incident_id != authoritative_incident_id:
        return "mismatch", "assertion_mismatch"
    if case_id is not None and case_id != authoritative_case_id:
        return "mismatch", "assertion_mismatch"
    return ("matched" if incident_id or case_id else "not_supplied"), None


def _require_webhook_authority(
    authorization_context: TenantAuthorizationContext, configured_tenant_id: str
) -> None:
    if authorization_context.tenant_id != configured_tenant_id:
        raise TenantAuthorizationError(
            "webhook processor authority is not scoped to configured tenant"
        )
    authorization_context.require_role(RequiredRole.REVIEWER)


def _is_safe_object_segment(value: str) -> bool:
    return bool(value) and all(character.isalnum() or character in ".-_" for character in value)


def _hex_identity(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "WebhookAssociationError",
    "WebhookProcessingError",
    "WebhookProcessingService",
]
