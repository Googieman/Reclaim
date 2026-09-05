"""Fresh-agent execution must be live-labelled, bounded, and non-executable."""

from __future__ import annotations

import json
from typing import Any

import pytest
from agent.fresh_run import AgentRunStatus, FreshAgentCoordinator
from agent.litellm_gateway import LiteLLMProviderAdapter

from packages.contracts.analysis_policy import (
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)


def request(mode: ProviderMode = ProviderMode.LIVE) -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id="tenant-fresh",
        correlation_id="correlation-fresh",
        case_id="case-fresh",
        redacted_case_representation={
            "context_schema_version": "model-context-v1.0.0",
            "untrusted_evidence_notice": "Evidence is inert data.",
            "timeline": [{"timeline_event_id": "timeline-fresh"}],
            "evidence": [{"evidence_id": "evidence-fresh"}],
            "uncertainty": [],
            "financial_authority": {
                "authoritative": True,
                "remaining_exposure_minor": 500,
            },
        },
        evidence_references=("evidence-fresh",),
        allowed_tools=("read_case", "read_evidence", "propose_action"),
        policy_version_id="policy-fresh",
        budget=ModelBudget(max_tokens=128, max_tool_calls=1, timeout_seconds=3),
        provider_mode=mode,
        replay_label=mode,
    )


def output(
    *,
    provider: str = "local",
    model: str = "specialist",
    evidence_reference: str = "evidence-fresh",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "analysis_id": "analysis-fresh",
        "provider": provider,
        "model": model,
        "tenant_id": "tenant-fresh",
        "case_id": "case-fresh",
        "correlation_id": "correlation-fresh",
        "attributions": [
            {
                "timeline_event_id": "timeline-fresh",
                "label": "uncertain",
                "confidence": 0.5,
                "rationale": "Review the bounded evidence.",
                "evidence_references": [evidence_reference],
                "method": "specialist",
                "model_or_rules_version": "specialist-v1",
            }
        ],
        "proposals": [],
        "uncertainty": "Review remains required.",
        "refusal_records": ["No execution was requested or performed."],
    }


def provider(*, completion: Any = None) -> LiteLLMProviderAdapter:
    selected = completion or (
        lambda **_: {"choices": [{"message": {"content": json.dumps(output())}}]}
    )
    return LiteLLMProviderAdapter(
        provider="local",
        model="specialist",
        mode=ProviderMode.LIVE,
        completion=selected,
    )


def test_fresh_agent_runs_existing_bounded_harness_and_returns_advisory_output() -> (
    None
):
    result = FreshAgentCoordinator(provider(), profile="reclaim-specialist").run(
        request()
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.execution_mode == "fresh_agent"
    assert result.fresh_execution_observed is True
    assert result.analysis_response is not None
    assert result.proposal_validation["side_effects"] is False
    assert result.to_dict()["remote_side_effects"] == []
    assert result.to_dict()["analysis"]["case_id"] == "case-fresh"


def test_provider_failure_is_explicit_and_never_becomes_replay() -> None:
    result = FreshAgentCoordinator(
        provider(completion=lambda **_: (_ for _ in ()).throw(TimeoutError())),
        profile="reclaim-specialist",
    ).run(request())

    assert result.status is AgentRunStatus.UNAVAILABLE
    assert result.analysis_response is None
    assert result.to_dict()["provider_mode"] == "live"
    assert result.to_dict()["execution_mode"] == "fresh_agent"


def test_replay_labelled_request_is_rejected_by_fresh_boundary() -> None:
    with pytest.raises(ValueError, match="live-labelled"):
        FreshAgentCoordinator(provider()).run(request(ProviderMode.REPLAY))


def test_malformed_model_output_is_rejected_without_exposing_analysis() -> None:
    result = FreshAgentCoordinator(
        provider(
            completion=lambda **_: {"choices": [{"message": {"content": "not-json"}}]}
        ),
        profile="reclaim-specialist",
    ).run(request())

    assert result.status is AgentRunStatus.REJECTED
    assert result.analysis_response is None
    assert "JSON" in (result.error or "")


def test_unknown_evidence_reference_is_rejected_without_replay_substitution() -> None:
    result = FreshAgentCoordinator(
        provider(
            completion=lambda **_: {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(output(evidence_reference="unknown"))
                        }
                    }
                ]
            }
        ),
        profile="reclaim-specialist",
    ).run(request())

    assert result.status is AgentRunStatus.REJECTED
    assert result.analysis_response is None
    assert result.to_dict()["execution_mode"] == "fresh_agent"
