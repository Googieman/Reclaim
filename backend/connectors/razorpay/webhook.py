"""Strict, original-payload verification for Razorpay Test Mode webhooks.

This module verifies an inbound provider message only.  It does not create a
case, publish an event, invoke a connector action, or treat provider fields as
authorization.  T048 owns durable processing after this trust decision.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.auth.oidc import TenantAuthorizationContext
from app.secrets.vault import VaultSecretStore, vault_webhook_secret_path
from packages.contracts.intake import IntakeStatus, RazorpayWebhookRequest


class WebhookVerificationError(ValueError):
    """Raised only for verifier configuration errors, never untrusted payload data."""


class WebhookSecretResolver(Protocol):
    def resolve(
        self, *, tenant_id: str, connector_id: str, reference: str
    ) -> str | bytes | Sequence[str | bytes]: ...


@dataclass(frozen=True, slots=True)
class WebhookVerification:
    """Authenticated or quarantined provider metadata with the original bytes."""

    tenant_id: str
    correlation_id: str
    connector_id: str
    status: IntakeStatus
    original_payload: bytes
    payload_checksum: str
    provider_event_id: str | None = None
    event_type: str | None = None
    event_timestamp: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status in {IntakeStatus.ACCEPTED, IntakeStatus.DUPLICATE}:
            if not self.provider_event_id:
                raise WebhookVerificationError(
                    "accepted webhook verification requires provider event identity"
                )
        elif not self.reason:
            raise WebhookVerificationError("quarantined webhook verification requires a reason")


class _VaultWebhookSecretResolver:
    def __init__(self, store: VaultSecretStore) -> None:
        self.store = store

    def resolve(
        self, *, tenant_id: str, connector_id: str, reference: str
    ) -> str | bytes | Sequence[str | bytes]:
        expected = vault_webhook_secret_path(tenant_id, connector_id)
        if reference != expected:
            raise WebhookVerificationError("webhook secret reference is not tenant scoped")
        material = self.store.read_webhook_secret(
            tenant_id=tenant_id,
            connector_id=connector_id,
        )
        secret = material.get("current") or material.get("secret") or material.get("webhook_secret")
        previous = material.get("previous")
        if secret is None:
            raise WebhookVerificationError("webhook secret material is missing")
        if previous is None:
            return secret
        return (secret, previous)


SecretResolver = WebhookSecretResolver | VaultSecretStore | Callable[..., str | bytes]

DEFAULT_SIGNATURE_HEADER = "X-Razorpay-Signature"
DEFAULT_PROVIDER_EVENT_ID_HEADER = "X-Razorpay-Event-Id"


class RazorpayWebhookVerifier:
    """Verify a configured tenant's Test Mode webhook without trusting its tenant field."""

    def __init__(
        self,
        *,
        configured_tenant_id: str,
        connector_id: str,
        secret_resolver: SecretResolver,
        secret_reference: str | None = None,
        signature_encoding: str = "hex",
    ) -> None:
        if not configured_tenant_id.strip() or not connector_id.strip():
            raise WebhookVerificationError("configured tenant and connector are required")
        if signature_encoding != "hex":
            raise WebhookVerificationError(
                "only Razorpay hexadecimal HMAC signatures are supported"
            )
        self.configured_tenant_id = configured_tenant_id
        self.connector_id = connector_id
        self.secret_reference = secret_reference or vault_webhook_secret_path(
            configured_tenant_id, connector_id
        )
        self.secret_resolver = (
            _VaultWebhookSecretResolver(secret_resolver)
            if isinstance(secret_resolver, VaultSecretStore)
            else secret_resolver
        )

    def verify(
        self,
        request: RazorpayWebhookRequest,
        *,
        authorization_context: TenantAuthorizationContext | None = None,
    ) -> WebhookVerification:
        """Return a quarantine outcome for every untrusted-data validation failure."""

        if authorization_context is not None and (
            authorization_context.tenant_id != self.configured_tenant_id
            or request.tenant_id != authorization_context.tenant_id
        ):
            return self._quarantine(request, "tenant does not match configured connector")
        if request.tenant_id != self.configured_tenant_id:
            return self._quarantine(request, "tenant does not match configured connector")
        if request.connector_id != self.connector_id:
            return self._quarantine(request, "connector does not match configured connector")

        actual_checksum = _payload_checksum(request.original_payload)
        if _normalize_checksum(request.payload_checksum) != actual_checksum:
            return self._quarantine(request, "payload checksum mismatch")
        if not request.signature:
            return self._quarantine(request, "missing provider signature")
        if not request.provider_event_id:
            return self._quarantine(request, "missing provider event identity")
        if not request.event_type or request.event_timestamp is None:
            return self._quarantine(request, "incomplete provider payload")

        try:
            body = json.loads(request.original_payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._quarantine(request, "provider payload is not valid JSON")
        if not isinstance(body, dict):
            return self._quarantine(request, "provider payload must be a JSON object")
        body_event_id = body.get("id") or body.get("event_id")
        if body_event_id is not None and body_event_id != request.provider_event_id:
            return self._quarantine(request, "provider event identity does not match payload")
        body_event_type = body.get("event") or body.get("type")
        if body_event_type is not None and body_event_type != request.event_type:
            return self._quarantine(request, "provider event type does not match payload")

        try:
            secrets = self._resolve_secrets()
        except (WebhookVerificationError, PermissionError, KeyError, TypeError):
            return self._quarantine(request, "provider verification secret is unavailable")
        if not any(
            _matches_signature(request.original_payload, request.signature, secret)
            for secret in secrets
        ):
            return self._quarantine(request, "invalid provider signature")

        return WebhookVerification(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            connector_id=request.connector_id,
            status=IntakeStatus.ACCEPTED,
            original_payload=request.original_payload,
            payload_checksum=actual_checksum,
            provider_event_id=request.provider_event_id,
            event_type=request.event_type,
            event_timestamp=request.event_timestamp,
        )

    def verify_http(
        self,
        *,
        correlation_id: str,
        original_payload: bytes,
        headers: Mapping[str, str],
        received_at: datetime,
        authorization_context: TenantAuthorizationContext | None = None,
    ) -> WebhookVerification:
        """Build a strict request from HTTP metadata and run the same verifier."""

        body: dict[str, Any] = {}
        try:
            parsed = json.loads(original_payload)
            if isinstance(parsed, dict):
                body = parsed
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        provider_event_id = _header(headers, DEFAULT_PROVIDER_EVENT_ID_HEADER) or _optional_text(
            body.get("id") or body.get("event_id")
        )
        event_type = _optional_text(body.get("event") or body.get("type"))
        event_timestamp = _parse_event_timestamp(body.get("created_at"))
        request = RazorpayWebhookRequest(
            tenant_id=self.configured_tenant_id,
            correlation_id=correlation_id,
            connector_id=self.connector_id,
            original_payload=original_payload,
            payload_checksum=_payload_checksum(original_payload),
            signature=_header(headers, DEFAULT_SIGNATURE_HEADER),
            provider_event_id=provider_event_id,
            event_type=event_type,
            event_timestamp=event_timestamp,
            received_at=received_at,
        )
        return self.verify(request, authorization_context=authorization_context)

    def _resolve_secrets(self) -> tuple[str | bytes, ...]:
        resolver = self.secret_resolver
        if hasattr(resolver, "resolve"):
            material = resolver.resolve(
                tenant_id=self.configured_tenant_id,
                connector_id=self.connector_id,
                reference=self.secret_reference,
            )
        elif callable(resolver):
            material = resolver(
                tenant_id=self.configured_tenant_id,
                connector_id=self.connector_id,
                reference=self.secret_reference,
            )
        else:
            raise WebhookVerificationError("webhook secret resolver is invalid")
        if isinstance(material, str | bytes):
            return (material,)
        values = tuple(material)
        if not values or any(not isinstance(value, str | bytes) for value in values):
            raise WebhookVerificationError("webhook secret resolver returned invalid material")
        return values

    def _quarantine(self, request: RazorpayWebhookRequest, reason: str) -> WebhookVerification:
        return WebhookVerification(
            tenant_id=self.configured_tenant_id,
            correlation_id=request.correlation_id,
            connector_id=request.connector_id,
            status=IntakeStatus.QUARANTINED,
            original_payload=request.original_payload,
            payload_checksum=_payload_checksum(request.original_payload),
            provider_event_id=request.provider_event_id,
            event_type=request.event_type,
            event_timestamp=request.event_timestamp,
            reason=reason,
        )


def _payload_checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _normalize_checksum(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized.startswith("sha256:") else f"sha256:{normalized}"


def _matches_signature(payload: bytes, supplied: str, secret: str | bytes) -> bool:
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    digest = hmac.new(key, payload, hashlib.sha256).hexdigest()
    candidate = supplied.strip().lower()
    if candidate.startswith("sha256="):
        candidate = candidate.removeprefix("sha256=")
    return hmac.compare_digest(candidate, digest)


def _header(headers: Mapping[str, str], expected_name: str) -> str | None:
    expected = expected_name.lower()
    for name, value in headers.items():
        if name.lower() == expected:
            return value.strip() or None
    return None


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _parse_event_timestamp(value: object) -> datetime | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    return None


def payload_checksum(payload: bytes) -> str:
    """Public helper used by the replay fixture and processing boundaries."""

    return _payload_checksum(payload)
