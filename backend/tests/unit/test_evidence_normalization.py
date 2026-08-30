"""Deterministic normalization and provenance preservation tests."""

from datetime import UTC, datetime

import pytest
from evidence.models import NormalizedFact
from evidence.normalization import EvidenceNormalizationError, normalize_response
from packages.contracts.connectors import EvidenceResponse


def response(**overrides: object) -> EvidenceResponse:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "correlation_id": "corr-1",
        "case_id": "case-1",
        "connector_id": "payments-read",
        "source_identity": "merchant-ledger",
        "resource_type": "payments",
        "observed_at": datetime(2026, 8, 30, 9, 0, tzinfo=UTC),
        "collected_at": datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
        "completeness": "complete",
        "raw_checksum": "sha256:raw",
        "connector_status": "complete",
        "normalized_facts": [
            {
                "source_event_id": "payment-event-1",
                "canonical_event_type": "payment.captured",
                "dedupe_key": "payment:p-1",
                "event_at": "2026-08-30T13:30:00+05:30",
                "provider_event_id": "provider-event-1",
                "payment_id": "p-1",
                "source_priority": 10,
            }
        ],
    }
    values.update(overrides)
    return EvidenceResponse(**values)


def test_normalization_uses_utc_and_preserves_original_provider_timestamps() -> None:
    fact = normalize_response(response(), evidence_id="evidence-1")[0]

    assert isinstance(fact, NormalizedFact)
    assert fact.effective_at == datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    assert fact.original_timestamps["event_at"] == "2026-08-30T13:30:00+05:30"
    assert fact.provider_identifiers == {
        "provider_event_id": "provider-event-1",
        "payment_id": "p-1",
    }


def test_normalization_precedence_falls_back_to_observed_then_received() -> None:
    no_event = response(
        normalized_facts=[
            {
                "source_event_id": "event-observed",
                "canonical_event_type": "payment.authorized",
            }
        ]
    )
    observed = normalize_response(no_event, evidence_id="evidence-1")[0]
    assert observed.effective_at == datetime(2026, 8, 30, 9, 0, tzinfo=UTC)

    explicit_missing_observed = response(
        normalized_facts=[
            {
                "source_event_id": "event-received",
                "canonical_event_type": "payment.authorized",
                "observed_at": None,
            }
        ]
    )
    received_fallback = normalize_response(explicit_missing_observed, evidence_id="evidence-1")[0]
    assert received_fallback.effective_at == datetime(2026, 8, 30, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "fact",
    (
        {"canonical_event_type": "payment.captured"},
        {"source_event_id": "event-1"},
        {
            "source_event_id": "event-1",
            "canonical_event_type": "payment.captured",
            "event_at": datetime(2026, 8, 30, 9, 0),
        },
        {
            "source_event_id": "event-1",
            "canonical_event_type": "payment.captured",
            "source_priority": -1,
        },
    ),
)
def test_malformed_fact_fails_closed_without_inventing_a_normalized_fact(
    fact: dict[str, object],
) -> None:
    with pytest.raises(EvidenceNormalizationError):
        normalize_response(response(normalized_facts=[fact]), evidence_id="evidence-1")


def test_fact_tenant_content_cannot_cross_the_response_tenant() -> None:
    with pytest.raises(EvidenceNormalizationError, match="tenant boundary"):
        normalize_response(
            response(
                normalized_facts=[
                    {
                        "tenant_id": "tenant-b",
                        "source_event_id": "event-1",
                        "canonical_event_type": "payment.captured",
                    }
                ]
            ),
            evidence_id="evidence-1",
        )
