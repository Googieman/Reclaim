"""Uncertainty propagation expectations across the US1-to-US2 boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.auth.oidc import IdentityType, TenantAuthorizationContext
from packages.contracts.analysis_policy import (
    ActionType,
    AttributionLabel,
    AttributionSuggestion,
    ModelAnalysisResponse,
    PolicyDecision,
    PolicyResult,
    TypedActionProposal,
)
from us2_test_seams import require_symbol
from timeline.reconstruct import TimelineReconstructor
from evidence.models import NormalizedFact


TENANT_ID = "tenant-us2-uncertainty"
CASE_ID = "case-us2-uncertainty"
TIMESTAMP = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def conflicting_facts() -> tuple[NormalizedFact, NormalizedFact]:
    common = {
        "tenant_id": TENANT_ID,
        "case_id": CASE_ID,
        "resource_type": "payments",
        "canonical_event_type": "payment.captured",
        "dedupe_key": "payment:uncertain-1",
        "effective_at": TIMESTAMP,
        "observed_at": TIMESTAMP,
        "received_at": TIMESTAMP,
        "event_at": TIMESTAMP,
        "provider_identifiers": {"payment_id": "pay-uncertain-1"},
    }
    return (
        NormalizedFact(
            **common,
            evidence_id="evidence-provider-uncertain",
            source_identity="payment-provider",
            source_event_id="provider-event-uncertain",
            source_priority=10,
            payload={"status": "captured", "amount_minor": 7_500},
            evidence_references=("evidence-provider-uncertain",),
        ),
        NormalizedFact(
            **common,
            evidence_id="evidence-ledger-uncertain",
            source_identity="merchant-ledger",
            source_event_id="ledger-event-uncertain",
            source_priority=20,
            payload={"status": "authorized", "amount_minor": 7_500},
            evidence_references=("evidence-ledger-uncertain",),
        ),
    )


def uncertain_timeline_event() -> Any:
    result = TimelineReconstructor().rebuild(
        case_id=CASE_ID,
        evidence=(),
        normalized_facts=conflicting_facts(),
        authorization_context=TenantAuthorizationContext(
            subject="reviewer-us2-uncertainty",
            tenant_id=TENANT_ID,
            roles=frozenset({"reviewer"}),
            identity_type=IdentityType.USER,
            issuer="https://issuer.reclaim.test",
        ),
    )
    assert len(result.events) == 1
    return result.events[0]


def uncertain_attribution() -> AttributionSuggestion:
    event = uncertain_timeline_event()
    return AttributionSuggestion(
        timeline_event_id=event.timeline_event_id,
        label=AttributionLabel.UNCERTAIN,
        confidence=0.5,
        rationale="Conflicting payment sources require human review.",
        evidence_references=event.evidence_references,
        method="rules",
        model_or_rules_version="rules-v1.0.0",
    )


def test_authoritative_timeline_conflict_retains_uncertainty_and_provenance() -> None:
    first, second = conflicting_facts()
    before = (first.payload.copy(), second.payload.copy(), first.evidence_references)
    event = uncertain_timeline_event()

    assert event.uncertainty_reasons == ("conflicting_sources",)
    assert set(event.conflicting_source_event_ids) == {
        "ledger-event-uncertain",
    }
    assert event.evidence_references == (
        "evidence-ledger-uncertain",
        "evidence-provider-uncertain",
    )
    assert (first.payload, second.payload, first.evidence_references) == before


def test_uncertainty_is_explicit_in_analysis_proposal_and_policy_contracts() -> None:
    attribution = uncertain_attribution()
    response = ModelAnalysisResponse(
        tenant_id=TENANT_ID,
        correlation_id="corr-us2-uncertainty",
        analysis_id="analysis-us2-uncertainty",
        provider="replay-fixture",
        model="deterministic-boundary",
        attributions=(attribution,),
        uncertainty="uncertain attribution requires review",
    )
    proposal = TypedActionProposal(
        tenant_id=TENANT_ID,
        correlation_id="corr-us2-uncertainty",
        proposal_id="proposal-us2-uncertainty",
        case_id=CASE_ID,
        action_type=ActionType.HOLD_FULFILLMENT,
        target_resource="order-uncertain-1",
        rationale="Hold pending human review of conflicting evidence.",
        evidence_references=attribution.evidence_references,
        attribution_references=(attribution.timeline_event_id,),
        idempotency_key="proposal-us2-uncertainty-key",
        analysis_id=response.analysis_id,
    )
    policy = PolicyDecision(
        tenant_id=TENANT_ID,
        correlation_id="corr-us2-uncertainty",
        decision_id="decision-us2-uncertainty",
        case_id=CASE_ID,
        proposal_id=proposal.proposal_id,
        policy_version_id="policy-v1.0.0",
        result=PolicyResult.ESCALATE,
        evaluated_conditions={
            "attribution_labels": [AttributionLabel.UNCERTAIN.value],
            "uncertainty_preserved": True,
            "review_required": True,
        },
        evaluator_version="policy-evaluator-v1.0.0",
        decided_at=TIMESTAMP,
    )

    assert response.attributions[0].label is AttributionLabel.UNCERTAIN
    assert response.uncertainty == "uncertain attribution requires review"
    assert proposal.attribution_references == (attribution.timeline_event_id,)
    assert policy.result is PolicyResult.ESCALATE
    assert policy.evaluated_conditions["uncertainty_preserved"] is True


@pytest.mark.xfail(
    strict=True,
    reason="T062 propagation is expected red until the later US2 analysis components exist",
)
def test_uncertain_timeline_input_stays_uncertain_through_proposal_and_policy_inputs() -> (
    None
):
    propagate = require_symbol(
        "analysis.deterministic_summary",
        "propagate_uncertainty",
        task="T062/T069",
    )
    event = uncertain_timeline_event()
    attribution = uncertain_attribution()
    outcome = propagate(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        timeline_events=(event,),
        attributions=(attribution,),
    )

    assert outcome["attribution_labels"] == {
        event.timeline_event_id: AttributionLabel.UNCERTAIN.value
    }
    assert outcome["proposal_inputs"][0]["label"] == AttributionLabel.UNCERTAIN.value
    assert outcome["policy_inputs"]["uncertain_event_ids"] == [event.timeline_event_id]
    assert outcome["review_or_escalation"] is True


@pytest.mark.xfail(
    strict=True,
    reason="T062 missing-evidence behavior is expected red until the later US2 analysis components exist",
)
def test_missing_evidence_cannot_be_fabricated_into_certain_attribution() -> None:
    propagate = require_symbol(
        "analysis.deterministic_summary",
        "propagate_uncertainty",
        task="T062/T069",
    )
    outcome = propagate(
        tenant_id=TENANT_ID,
        case_id=CASE_ID,
        timeline_events=(uncertain_timeline_event(),),
        attributions=(),
    )

    assert outcome["unknown_event_ids"]
    assert all(
        label == AttributionLabel.UNCERTAIN.value
        for label in outcome["labels"].values()
    )
