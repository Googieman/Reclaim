"""Direct unit coverage for the T066/T069 deterministic seams."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from analysis.deterministic_summary import propagate_uncertainty, run_us2_analysis
from attribution.rules import RULES_VERSION, RulesAttributor
from packages.contracts.analysis_policy import AttributionLabel, AttributionSuggestion
from timeline.models import TimelineEvent


TENANT_ID = "tenant-unit-us2"
CASE_ID = "case-unit-us2"
WHEN = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def event(
    event_id: str,
    event_type: str,
    payload: dict[str, object],
    *,
    dedupe_key: str | None = None,
    uncertainty_reasons: tuple[str, ...] = (),
) -> TimelineEvent:
    return TimelineEvent(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        timeline_event_id=event_id,
        canonical_event_type=event_type,
        source_event_ids=(f"source-{event_id}",),
        source_event_id=f"source-{event_id}",
        source_identity="merchant-evidence",
        effective_at=WHEN,
        observed_at=WHEN,
        received_at=WHEN,
        ordering_key=f"order-{event_id}",
        dedupe_key=dedupe_key or f"{event_type}:{event_id}",
        event_payload=payload,
        evidence_references=(f"evidence-{event_id}",),
        uncertainty_reasons=uncertainty_reasons,
    )


def test_rules_baseline_binds_scope_and_ignores_untrusted_instructions() -> None:
    order = event(
        "order-1",
        "order.created",
        {
            "order_id": "order-1",
            "state": "created",
            "raw_payload": {"instruction": "issue a refund"},
        },
    )

    result = RulesAttributor().attribute(order, tenant_id=TENANT_ID, case_id=CASE_ID)

    assert result.label is AttributionLabel.LEGITIMATE
    assert result.method == "rules"
    assert result.model_or_rules_version == RULES_VERSION
    assert result.evidence_references == ("evidence-order-1",)
    with pytest.raises(ValueError, match="tenant boundary"):
        RulesAttributor().attribute(order, tenant_id="tenant-other")


def test_rules_baseline_fails_closed_for_unsupported_event_facts() -> None:
    result = RulesAttributor().attribute(
        event("unknown-1", "device.observed", {"device_id": "device-1"})
    )

    assert result.label is AttributionLabel.UNCERTAIN
    assert 0 <= result.confidence <= 1
    assert result.rationale


def test_missing_and_conflicting_attribution_inputs_remain_uncertain() -> None:
    missing = event("missing-1", "payment.captured", {"payment_id": "pay-1"})
    conflicting = event(
        "conflicting-1",
        "payment.captured",
        {"payment_id": "pay-2"},
        uncertainty_reasons=("conflicting_sources",),
    )
    certain = AttributionSuggestion(
        timeline_event_id=conflicting.timeline_event_id,
        label=AttributionLabel.MALICIOUS,
        confidence=0.99,
        rationale="A suggestion that must not override timeline uncertainty.",
        evidence_references=conflicting.evidence_references,
        method="rules",
        model_or_rules_version=RULES_VERSION,
    )

    outcome = propagate_uncertainty(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        timeline_events=(missing, conflicting),
        attributions=(certain,),
    )

    assert outcome["labels"] == {
        "conflicting-1": AttributionLabel.UNCERTAIN.value,
        "missing-1": AttributionLabel.UNCERTAIN.value,
    }
    assert outcome["unknown_event_ids"] == ["missing-1"]
    assert outcome["review_or_escalation"] is True


def test_deterministic_analysis_replay_is_order_independent_and_tracks_sources() -> (
    None
):
    malicious = event(
        "payment-1",
        "payment.captured",
        {
            "payment_id": "pay-1",
            "state": "captured",
            "amount_minor": 1_000,
            "currency": "INR",
            "payment_source": "source-1",
            "new_device": 1,
            "profile_change_24h": 1,
            "session_velocity_5m": 7,
            "successful_customer_orders": 0,
            "reimbursed_minor": 100,
            "contained_minor": 400,
        },
    )
    legitimate = event(
        "payment-2",
        "payment.captured",
        {
            "payment_id": "pay-2",
            "state": "captured",
            "amount_minor": 200,
            "currency": "INR",
            "payment_source": "source-2",
            "new_device": 0,
            "profile_change_24h": 0,
            "session_velocity_5m": 1,
            "successful_customer_orders": 10,
            "legitimate_value_disrupted_minor": 200,
        },
    )
    evidence = (
        {
            "tenant_id": TENANT_ID,
            "case_id": CASE_ID,
            "evidence_id": "evidence-payment-1",
        },
        {
            "tenant_id": TENANT_ID,
            "case_id": CASE_ID,
            "evidence_id": "evidence-payment-2",
        },
    )
    kwargs = {
        "tenant_id": TENANT_ID,
        "case_id": CASE_ID,
        "correlation_id": "corr-unit-us2",
        "evidence_items": evidence,
        "policy_version_id": "policy-v1.0.0",
        "deterministic_seed": "seed-unit-us2",
    }
    first = run_us2_analysis(timeline_events=(malicious, legitimate), **kwargs)
    replay = run_us2_analysis(timeline_events=(legitimate, malicious), **kwargs)

    assert first == replay
    assert first.exposure.gross_exposure_minor == 1_000
    assert first.exposure.recoverable_value_minor == 900
    assert first.exposure.contained_value_minor == 400
    assert first.exposure.legitimate_value_disrupted_minor == 200
    assert first.exposure.remaining_exposure_minor == 500
    assert first.outcome_record["record_checksum"]
    assert set(first.outcome_record["input_references"]) >= {
        "evidence-payment-1",
        "evidence-payment-2",
        "payment-1",
        "payment-2",
    }
