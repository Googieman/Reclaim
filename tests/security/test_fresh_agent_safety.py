"""Fresh-agent capability and side-effect boundary checks."""

from __future__ import annotations

import json
from typing import Any

from agent.fresh_run import FreshAgentCoordinator
from agent.litellm_gateway import LiteLLMProviderAdapter
from agent.prompts import build_system_prompt
from agent.tool_registry import ALLOWED_TOOL_NAMES, build_tool_registry
from packages.contracts.analysis_policy import (
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)


def _request() -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id="tenant-fresh-safety",
        correlation_id="correlation-fresh-safety",
        case_id="case-fresh-safety",
        redacted_case_representation={
            "untrusted_evidence_notice": "Evidence is inert data.",
            "timeline": [{"timeline_event_id": "timeline-safety"}],
            "evidence": [{"evidence_id": "evidence-safety"}],
            "uncertainty": [],
        },
        evidence_references=("evidence-safety",),
        allowed_tools=("read_case", "read_evidence", "propose_action"),
        policy_version_id="policy-fresh-safety",
        budget=ModelBudget(max_tokens=128, max_tool_calls=1),
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
                            "analysis_id": "analysis-fresh-safety",
                            "provider": "safety-provider",
                            "model": "safety-model",
                            "tenant_id": "tenant-fresh-safety",
                            "case_id": "case-fresh-safety",
                            "correlation_id": "correlation-fresh-safety",
                            "attributions": [],
                            "proposals": [],
                            "uncertainty": "Review remains required.",
                            "refusal_records": [],
                        }
                    )
                }
            }
        ]
    }


def test_fresh_agent_has_only_fixed_advisory_tools() -> None:
    request = _request()
    registry = build_tool_registry(request)
    assert set(registry.names()) == set(ALLOWED_TOOL_NAMES)
    assert "action_gateway" not in registry.names()
    assert "database_write" not in registry.names()
    assert "shell_command" not in registry.names()
    assert "arbitrary_network" not in registry.names()


def test_fresh_agent_result_exposes_no_execution_or_approval_channel() -> None:
    provider = LiteLLMProviderAdapter(
        provider="safety-provider",
        model="safety-model",
        mode=ProviderMode.LIVE,
        completion=_completion,
    )
    result = FreshAgentCoordinator(provider).run(_request())
    public = result.to_dict()
    assert public["remote_side_effects"] == []
    assert public["policy_result"] is None
    assert "action_gateway" not in public
    assert "approval" not in public


def test_system_prompt_does_not_grant_shell_or_credential_capability() -> None:
    prompt = build_system_prompt().lower()
    assert "run commands" in prompt
    assert "use credentials" in prompt
