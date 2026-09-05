"""Prompt and context limits are deterministic trust-boundary checks."""

from __future__ import annotations

import pytest
from agent.litellm_gateway import build_model_input
from agent.prompts import MAX_CONTEXT_BYTES, bounded_context_json, build_system_prompt

from packages.contracts.analysis_policy import (
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)


def test_system_prompt_declares_untrusted_evidence_and_no_side_effects() -> None:
    prompt = build_system_prompt()
    assert "UNTRUSTED DATA" in prompt
    assert "Never request a database write" in prompt
    assert "chain-of-thought" in prompt


def test_context_serializer_fails_closed_at_byte_boundary() -> None:
    with pytest.raises(ValueError, match="byte bound"):
        bounded_context_json({"evidence": "x" * 20}, max_bytes=10)


def test_litellm_payload_uses_bounded_context_and_does_not_include_transport_secrets() -> (
    None
):
    request = ModelAnalysisRequest(
        tenant_id="tenant-prompt",
        correlation_id="correlation-prompt",
        case_id="case-prompt",
        redacted_case_representation={
            "token": "should not be secret material",
            "value": "safe",
        },
        policy_version_id="policy-prompt",
        budget=ModelBudget(max_tokens=32),
        provider_mode=ProviderMode.LIVE,
        replay_label=ProviderMode.LIVE,
    )
    payload = build_model_input(request)
    assert len(payload["messages"][1]["content"].encode("utf-8")) < MAX_CONTEXT_BYTES
    assert "api_key" not in payload["messages"][1]["content"]
