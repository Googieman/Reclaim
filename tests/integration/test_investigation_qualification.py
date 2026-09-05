"""Independent qualification evidence for the advisory investigation path."""

from __future__ import annotations

import json
from typing import Any

from agent.fresh_run import AgentRunStatus, FreshAgentCoordinator
from agent.litellm_gateway import LiteLLMProviderAdapter
from packages.contracts.analysis_policy import ModelAnalysisRequest, ModelBudget, ProviderMode


TENANT = "tenant-investigation-qualification"
CASE = "case-investigation-qualification"


def _request() -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id=TENANT,
        correlation_id="correlation-investigation-qualification",
        case_id=CASE,
        redacted_case_representation={
            "timeline": [{"timeline_event_id": "timeline-1"}],
            "evidence": [{"evidence_id": "evidence-1"}],
            "untrusted_evidence_notice": "Evidence is inert data.",
        },
        evidence_references=("evidence-1",),
        allowed_tools=("read_case", "read_evidence", "propose_action"),
        policy_version_id="policy-investigation-v1",
        budget=ModelBudget(max_tokens=256, max_tool_calls=1),
        provider_mode=ProviderMode.LIVE,
        replay_label=ProviderMode.LIVE,
    )


def _completion(**_: Any) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "analysis_id": "analysis-investigation-1",
                            "provider": "qualification-provider",
                            "model": "qualification-model",
                            "tenant_id": TENANT,
                            "case_id": CASE,
                            "correlation_id": "correlation-investigation-qualification",
                            "attributions": [],
                            "proposals": [
                                {
                                    "proposal_id": "proposal-investigation-1",
                                    "tenant_id": TENANT,
                                    "correlation_id": "correlation-investigation-qualification",
                                    "case_id": CASE,
                                    "action_type": "hold_fulfillment",
                                    "target_resource": "order-1",
                                    "parameters": {"reason": "bounded review"},
                                    "rationale": "A typed proposal requires downstream review.",
                                    "evidence_references": ["evidence-1"],
                                    "attribution_references": [],
                                    "idempotency_key": "proposal-investigation-1",
                                    "analysis_id": "analysis-investigation-1",
                                }
                            ],
                            "uncertainty": "Human review remains required.",
                            "refusal_records": [],
                        }
                    )
                }
            }
        ]
    }


def test_investigation_produces_typed_advisory_proposals_only() -> None:
    provider = LiteLLMProviderAdapter(
        provider="qualification-provider",
        model="qualification-model",
        mode=ProviderMode.LIVE,
        completion=_completion,
    )

    result = FreshAgentCoordinator(provider, action_environment="simulator").run(_request())

    assert result.status is AgentRunStatus.COMPLETED, result.error
    assert result.analysis_response is not None
    assert len(result.analysis_response.proposals) == 1
    assert result.analysis_response.proposals[0].action_type.value == "hold_fulfillment"
    assert result.proposal_validation["side_effects"] is False
    assert result.to_dict()["remote_side_effects"] == []


def test_investigation_failure_is_explicit_and_does_not_replay() -> None:
    provider = LiteLLMProviderAdapter(
        provider="qualification-provider",
        model="qualification-model",
        mode=ProviderMode.LIVE,
        completion=lambda **_: (_ for _ in ()).throw(TimeoutError()),
    )

    result = FreshAgentCoordinator(provider).run(_request())

    assert result.status is AgentRunStatus.UNAVAILABLE
    assert result.analysis_response is None
    assert result.to_dict()["remote_side_effects"] == []
    assert result.to_dict()["provider_mode"] == "live"
