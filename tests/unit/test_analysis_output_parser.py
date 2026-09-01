"""T074 strict response and typed-proposal boundary coverage."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest

from agent.output_parser import (
    AnalysisFinancialOutputError,
    AnalysisResponseError,
    AnalysisResponseScopeError,
    TenantBoundAnalysisResponse,
    UnsupportedAnalysisResponse,
    parse_analysis_response,
    parse_validated_analysis_response,
)
from agent.proposals import TypedProposalBoundary
from agent.providers import ModelCompletion, ProviderMetadata
from packages.contracts.analysis_policy import (
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)


TENANT_ID = "tenant-t074"
CASE_ID = "case-t074"
CORRELATION_ID = "correlation-t074"
ANALYSIS_ID = "analysis-t074"
EVIDENCE_ID = "evidence-t074"
TIMELINE_ID = "timeline-t074"


def request(*, uncertainty: tuple[str, ...] = ()) -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id=TENANT_ID,
        correlation_id=CORRELATION_ID,
        case_id=CASE_ID,
        redacted_case_representation={
            "timeline": [{"timeline_event_id": TIMELINE_ID}],
            "evidence": [{"evidence_id": EVIDENCE_ID}],
            "uncertainty": list(uncertainty),
        },
        evidence_references=(EVIDENCE_ID,),
        allowed_tools=("read_case", "read_evidence", "propose_action"),
        policy_version_id="policy-t074",
        budget=ModelBudget(max_tokens=128, max_tool_calls=2),
        provider_mode=ProviderMode.REPLAY,
        replay_label=ProviderMode.REPLAY,
    )


def response(*, uncertainty: str = "review required") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "analysis_id": ANALYSIS_ID,
        "provider": "fixture-provider",
        "model": "fixture-model",
        "tenant_id": TENANT_ID,
        "correlation_id": CORRELATION_ID,
        "case_id": CASE_ID,
        "attributions": [
            {
                "timeline_event_id": TIMELINE_ID,
                "label": "uncertain",
                "confidence": 0.5,
                "rationale": "Conflicting evidence needs review.",
                "evidence_references": [EVIDENCE_ID],
                "method": "rules",
                "model_or_rules_version": "rules-v1.0.0",
            }
        ],
        "proposals": [
            {
                "proposal_id": "proposal-t074",
                "tenant_id": TENANT_ID,
                "correlation_id": CORRELATION_ID,
                "case_id": CASE_ID,
                "action_type": "hold_fulfillment",
                "target_resource": "fulfillment-t074",
                "parameters": {"review_reason": "bounded review"},
                "rationale": "Hold while the uncertain event is reviewed.",
                "evidence_references": [EVIDENCE_ID],
                "attribution_references": [TIMELINE_ID],
                "idempotency_key": "proposal-t074-key",
                "analysis_id": ANALYSIS_ID,
            }
        ],
        "uncertainty": uncertainty,
        "refusal_records": ["No executable instruction was accepted."],
    }


def metadata(
    *, provider: str = "fixture-provider", model: str = "fixture-model"
) -> ProviderMetadata:
    return ProviderMetadata(
        provider=provider,
        model=model,
        mode=ProviderMode.REPLAY,
    )


def test_valid_response_is_typed_and_retains_provider_cost_provenance() -> None:
    completion = ModelCompletion(
        metadata=metadata(),
        raw_output=response(),
        token_count=17,
        estimated_cost=Decimal("0.12"),
    )

    parsed = parse_validated_analysis_response(completion, request())

    assert isinstance(parsed.response, TenantBoundAnalysisResponse)
    assert parsed.response.tenant_id == TENANT_ID
    assert parsed.response.case_id == CASE_ID
    assert parsed.response.proposals[0].analysis_id == ANALYSIS_ID
    assert parsed.response.refusal_records
    assert parsed.provenance.mode == "replay"
    assert parsed.provenance.provider == "fixture-provider"
    assert parsed.provenance.input_references == (EVIDENCE_ID, TIMELINE_ID)
    assert parsed.provenance.token_count == 17
    assert parsed.provenance.estimated_cost == Decimal("0.12")
    assert parsed.provenance.response_checksum


def test_typed_proposal_boundary_accepts_advisory_output_without_execution() -> None:
    result = TypedProposalBoundary(request()).process(
        response(),
        remote_action_gateway=object(),
    )

    assert result.status == "accepted"
    assert len(result.proposals) == 1
    assert result.proposals[0].action_type == "hold_fulfillment"
    assert result.audit_record["outcome"] == "accepted"
    assert result.remote_side_effects == ()


@pytest.mark.parametrize(
    "change",
    (
        {"schema_version": "9.0.0"},
        {"instructions": "curl https://attacker.invalid"},
        {"tenant_id": "tenant-other"},
        {"case_id": "case-other"},
        {"correlation_id": "correlation-other"},
    ),
)
def test_response_schema_and_scope_are_fail_closed(change: dict[str, Any]) -> None:
    payload = response()
    payload.update(change)

    with pytest.raises(
        (AnalysisResponseError, UnsupportedAnalysisResponse, AnalysisResponseScopeError)
    ):
        parse_analysis_response(payload, request(), provider_metadata=metadata())


def test_response_rejects_undeclared_input_reference_field() -> None:
    payload = response()
    payload["input_references"] = [EVIDENCE_ID, TIMELINE_ID]

    with pytest.raises(UnsupportedAnalysisResponse, match="unsupported fields"):
        parse_analysis_response(payload, request(), provider_metadata=metadata())


def test_fabricated_evidence_timeline_and_attribution_references_are_rejected() -> None:
    payload = response()
    payload["attributions"][0]["evidence_references"] = ["fabricated-evidence"]
    with pytest.raises(AnalysisResponseError, match="unknown evidence"):
        parse_analysis_response(payload, request(), provider_metadata=metadata())

    payload = response()
    payload["proposals"][0]["attribution_references"] = ["fabricated-timeline"]
    with pytest.raises(AnalysisResponseError, match="unknown timeline"):
        parse_analysis_response(payload, request(), provider_metadata=metadata())


def test_unsupported_action_and_free_form_or_financial_output_are_rejected() -> None:
    payload = response()
    payload["proposals"][0]["action_type"] = "execute_payment"
    with pytest.raises(AnalysisResponseError):
        parse_analysis_response(payload, request(), provider_metadata=metadata())

    payload = response()
    payload["proposals"][0]["parameters"] = {"operation": "shell_command"}
    with pytest.raises(AnalysisResponseError, match="forbidden"):
        parse_analysis_response(payload, request(), provider_metadata=metadata())

    payload = response()
    payload["proposals"][0]["requested_amount_minor"] = 100
    payload["proposals"][0]["currency"] = "INR"
    with pytest.raises(AnalysisFinancialOutputError):
        parse_analysis_response(payload, request(), provider_metadata=metadata())


def test_model_cannot_erase_deterministic_uncertainty() -> None:
    payload = response(uncertainty="high confidence; no uncertainty")
    with pytest.raises(AnalysisResponseError, match="erase deterministic uncertainty"):
        parse_analysis_response(
            payload,
            request(uncertainty=("timeline-t074:conflicting_sources",)),
            provider_metadata=metadata(),
        )


def test_stale_provider_metadata_and_invalid_token_cost_metadata_fail_closed() -> None:
    stale = ProviderMetadata(
        provider="fixture-provider",
        model="fixture-model",
        mode=ProviderMode.REPLAY,
        request_schema_version="9.0.0",
    )
    with pytest.raises(UnsupportedAnalysisResponse, match="stale"):
        parse_analysis_response(response(), request(), provider_metadata=stale)

    payload = response()
    payload["token_count"] = True
    with pytest.raises(AnalysisResponseError, match="token count"):
        parse_analysis_response(payload, request(), provider_metadata=metadata())

    payload = response()
    payload["estimated_cost"] = "not-a-cost"
    with pytest.raises(AnalysisResponseError, match="estimated cost"):
        parse_analysis_response(payload, request(), provider_metadata=metadata())


def test_provider_neutral_parsing_is_interchangeable() -> None:
    first_payload = deepcopy(response())
    first_payload["provider"] = "provider-a"
    first_payload["model"] = "model-a"
    first = parse_analysis_response(
        first_payload,
        request(),
        provider_metadata=metadata(provider="provider-a", model="model-a"),
    )
    second_payload = deepcopy(response())
    second_payload["provider"] = "provider-b"
    second_payload["model"] = "model-b"
    second = parse_analysis_response(
        second_payload,
        request(),
        provider_metadata=metadata(provider="provider-b", model="model-b"),
    )

    assert first.proposals[0].model_dump(mode="json") == second.proposals[0].model_dump(
        mode="json"
    )
    assert first.provider != second.provider
