"""Deterministic normalization of untrusted connector facts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from packages.contracts.connectors import EvidenceResponse

from .models import NormalizedFact


class EvidenceNormalizationError(ValueError):
    """Raised when connector data cannot be normalized without inventing facts."""


def normalize_response(
    response: EvidenceResponse,
    *,
    evidence_id: str,
) -> tuple[NormalizedFact, ...]:
    """Normalize every fact or fail the response closed with no partial invention."""

    normalized: list[NormalizedFact] = []
    for index, raw_fact in enumerate(response.normalized_facts):
        if not isinstance(raw_fact, Mapping):
            raise EvidenceNormalizationError(f"evidence fact {index} is not an object")
        normalized.append(_normalize_fact(response, raw_fact, evidence_id=evidence_id, index=index))
    return tuple(
        sorted(
            normalized,
            key=lambda fact: (
                fact.effective_at,
                fact.canonical_event_type,
                fact.source_identity,
                fact.source_event_id,
                fact.evidence_id,
            ),
        )
    )


def _normalize_fact(
    response: EvidenceResponse,
    raw_fact: Mapping[str, Any],
    *,
    evidence_id: str,
    index: int,
) -> NormalizedFact:
    _check_fact_tenant(response, raw_fact, index)
    source_event_id = _required_text(raw_fact.get("source_event_id"), "source_event_id", index)
    canonical_event_type = _required_text(
        raw_fact.get("canonical_event_type") or raw_fact.get("event_type"),
        "canonical_event_type",
        index,
    )
    dedupe_key = raw_fact.get("dedupe_key")
    if dedupe_key is None:
        dedupe_key = f"{response.resource_type}:{source_event_id}"
    dedupe_key = _required_text(dedupe_key, "dedupe_key", index)

    event_at_raw = raw_fact.get("event_at")
    observed_at_raw = raw_fact.get("observed_at") or response.observed_at
    received_at_raw = raw_fact.get("received_at") or response.collected_at
    event_at = (
        _parse_timestamp(event_at_raw, "event_at", index) if event_at_raw is not None else None
    )
    observed_at = _parse_timestamp(observed_at_raw, "observed_at", index)
    received_at = _parse_timestamp(received_at_raw, "received_at", index)
    effective_at = event_at or observed_at or received_at

    raw_priority = raw_fact.get("source_priority", 100)
    if isinstance(raw_priority, bool) or not isinstance(raw_priority, int) or raw_priority < 0:
        raise EvidenceNormalizationError(f"evidence fact {index} source_priority is invalid")

    provider_identifiers = {
        key: value
        for key, value in raw_fact.items()
        if key
        in {
            "provider_event_id",
            "provider_id",
            "payment_id",
            "order_id",
            "session_id",
            "device_id",
            "profile_change_id",
            "fulfillment_id",
        }
        and isinstance(value, str)
        and value.strip()
    }
    original_timestamps = {
        "event_at": _original_timestamp(event_at_raw),
        "observed_at": _original_timestamp(observed_at_raw),
        "received_at": _original_timestamp(received_at_raw),
    }
    return NormalizedFact(
        tenant_id=response.tenant_id,
        case_id=response.case_id,
        evidence_id=evidence_id,
        resource_type=response.resource_type,
        source_identity=response.source_identity,
        source_event_id=source_event_id,
        canonical_event_type=canonical_event_type,
        dedupe_key=dedupe_key,
        effective_at=effective_at,
        observed_at=observed_at,
        received_at=received_at,
        event_at=event_at,
        source_priority=raw_priority,
        payload=dict(raw_fact),
        provider_identifiers=provider_identifiers,
        original_timestamps=original_timestamps,
        evidence_references=(evidence_id,),
    )


def _check_fact_tenant(
    response: EvidenceResponse,
    raw_fact: Mapping[str, Any],
    index: int,
) -> None:
    fact_tenant = raw_fact.get("tenant_id")
    if fact_tenant is not None and fact_tenant != response.tenant_id:
        raise EvidenceNormalizationError(f"evidence fact {index} crosses tenant boundary")


def _required_text(value: object, name: str, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceNormalizationError(f"evidence fact {index} {name} is required")
    return value.strip()


def _parse_timestamp(value: object, name: str, index: int) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceNormalizationError(f"evidence fact {index} {name} is malformed") from exc
    else:
        raise EvidenceNormalizationError(f"evidence fact {index} {name} is malformed")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceNormalizationError(f"evidence fact {index} {name} lacks explicit timezone")
    return parsed.astimezone(UTC)


def _original_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
