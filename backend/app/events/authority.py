"""Authority checks shared by the Redpanda transport boundary.

Redpanda carries bytes.  The only business authority for a domain event is the
PostgreSQL outbox row that was written in the same transaction as the business
change.  This module keeps the transport's syntactic checks separate from that
authoritative reconciliation step.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from typing import Any

from packages.contracts.common import CONTRACT_VERSION
from packages.contracts.events import EventEnvelope

from app.auth.oidc import IdentityType, TenantAuthorizationContext


class EventAuthorityError(ValueError):
    """Raised when a broker event cannot be authenticated as authoritative."""


# These are versioned component identities emitted by the current US1 writers.
# Adding a producer is an explicit code/configuration change, not an acceptance
# of arbitrary values supplied by a broker message.
AUTHORIZED_EVENT_PRODUCERS: frozenset[str] = frozenset(
    {
        "intake-api@1.0.0",
        "razorpay-webhook@1.0.0",
        "razorpay-webhook@2.0.0",
        "evidence-orchestrator@1.0.0",
        "timeline-reconstructor@1.0.0",
    }
)

# The current transport adapter receives an authenticated OIDC service context,
# not a broker-native mTLS principal.  These development/production-shaped
# service-account subjects are therefore the explicit application boundary.
# Production broker ACL/mTLS identity must be mapped to the same allowlist.
AUTHORIZED_EVENT_SERVICE_IDENTITIES: frozenset[str] = frozenset(
    {
        "reclaim-event-relay",
        "reclaim-incident-consumer",
        "reclaim-timeline-consumer",
        "reclaim-neo4j-projection",
        "service-account-reclaim-workflow",
        "service-account-reclaim-model-gateway",
        "service-account-reclaim-action-gateway",
        "reclaim-n8n-orchestrator",
    }
)


def payload_checksum(payload: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 digest used by event envelopes."""

    encoded = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_payload_checksum(event: EventEnvelope) -> None:
    """Reject an envelope whose declared checksum is not its payload digest."""

    declared = event.payload_checksum.strip().lower().removeprefix("sha256:")
    if declared != payload_checksum(event.payload):
        raise EventAuthorityError("event payload checksum does not match its envelope")


def require_supported_schema_version(event: EventEnvelope) -> None:
    """Reject event versions that this transport cannot interpret safely."""

    if event.schema_version != CONTRACT_VERSION:
        raise EventAuthorityError(
            f"unsupported authoritative event schema version: {event.schema_version!r}"
        )


def require_authorized_event_producer(
    producer: str,
    *,
    allowed_producers: Collection[str] = AUTHORIZED_EVENT_PRODUCERS,
) -> None:
    """Require the envelope producer to be an explicitly configured writer."""

    if producer not in allowed_producers:
        raise EventAuthorityError(f"event producer is not allowlisted: {producer!r}")


def require_authenticated_event_service(
    context: TenantAuthorizationContext,
    *,
    allowed_service_identities: Collection[str] = AUTHORIZED_EVENT_SERVICE_IDENTITIES,
) -> None:
    """Require an authenticated, allowlisted non-human transport service."""

    if context.identity_type is not IdentityType.SERVICE:
        raise EventAuthorityError("event transport requires an authenticated service identity")
    if "service" not in context.roles:
        raise EventAuthorityError("event transport service identity lacks the service role")
    if context.subject not in allowed_service_identities:
        raise EventAuthorityError(
            f"event transport service identity is not allowlisted: {context.subject!r}"
        )


__all__ = [
    "AUTHORIZED_EVENT_PRODUCERS",
    "AUTHORIZED_EVENT_SERVICE_IDENTITIES",
    "EventAuthorityError",
    "payload_checksum",
    "require_authenticated_event_service",
    "require_authorized_event_producer",
    "require_supported_schema_version",
    "validate_payload_checksum",
]
