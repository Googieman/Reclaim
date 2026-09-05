from __future__ import annotations

import json
from typing import Any

import pytest

from agent.providers import ModelProviderResponseError, ModelProviderUnavailable
from model_gateway.help_provider import (
    HelpModelProvider,
    build_help_provider,
)
from packages.contracts.help_chat import HelpGatewayRequest


def _request(**overrides: Any) -> HelpGatewayRequest:
    values: dict[str, Any] = {
        "question": "  How   do I verify a webhook? ",
        "passages": (
            "[intake.webhook-verification] Webhook verification: verify the original payload.",
            "[action.approval] Approval: review the typed proposal.",
        ),
    }
    values.update(overrides)
    return HelpGatewayRequest(**values)


def _completion(content: Any, *, tokens: int = 12) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"total_tokens": tokens},
    }


def test_provider_builds_a_bounded_prompt_and_validates_allowlisted_json() -> None:
    calls: list[dict[str, Any]] = []

    def complete(**payload: Any) -> dict[str, Any]:
        calls.append(payload)
        return _completion(
            json.dumps(
                {
                    "answer": "Verify the original webhook payload.",
                    "source_ids": ["intake.webhook-verification"],
                }
            )
        )

    provider = HelpModelProvider(
        model="deepseek-test",
        api_base="http://model-help.test/v1",
        api_key="model-secret",
        completion=complete,
    )

    result = provider.complete(_request())

    assert result.final_text == "Verify the original webhook payload."
    assert result.source_ids == ("intake.webhook-verification",)
    assert result.model_revision == "deepseek-test"
    assert result.token_count == 12
    assert calls[0]["model"] == "openai/deepseek-test"
    assert calls[0]["api_base"] == "http://model-help.test/v1"
    assert calls[0]["api_key"] == "model-secret"
    assert calls[0]["max_tokens"] == 1024
    assert "tools" not in calls[0]
    assert calls[0]["messages"][0]["role"] == "system"
    assert "tools" in calls[0]["messages"][0]["content"].lower()
    prompt = json.loads(calls[0]["messages"][1]["content"])
    assert prompt == {
        "question": "How do I verify a webhook?",
        "passages": [
            "[intake.webhook-verification] Webhook verification: verify the original payload.",
            "[action.approval] Approval: review the typed proposal.",
        ],
    }
    assert "model-secret" not in calls[0]["messages"][1]["content"]


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ('{"answer":"<think>private</think>","source_ids":["intake.webhook-verification"]}', "reasoning"),
        ('{"answer":"","source_ids":["intake.webhook-verification"]}', "answer"),
        ('{"source_ids":["intake.webhook-verification"]}', "answer"),
        ('{"answer":"safe","source_ids":["not-requested"]}', "source"),
        ('{"answer":"safe","source_ids":[]}', "source"),
        ("not json", "JSON"),
    ],
)
def test_provider_rejects_unsafe_or_malformed_model_output(content: str, match: str) -> None:
    provider = HelpModelProvider(
        model="deepseek-test",
        api_base="http://model-help.test/v1",
        api_key="model-secret",
        completion=lambda **_: _completion(content),
    )

    with pytest.raises(ModelProviderResponseError, match=match):
        provider.complete(_request())


def test_provider_rejects_analysis_markers_and_extra_output_keys() -> None:
    provider = HelpModelProvider(
        model="deepseek-test",
        api_base="http://model-help.test/v1",
        api_key="model-secret",
        completion=lambda **_: _completion(
            json.dumps(
                {
                    "answer": "safe",
                    "source_ids": ["intake.webhook-verification"],
                    "analysis": "hidden",
                }
            )
        ),
    )

    with pytest.raises(ModelProviderResponseError, match="keys"):
        provider.complete(_request())


def test_provider_converts_transport_failure_to_safe_unavailable_error() -> None:
    provider = HelpModelProvider(
        model="deepseek-test",
        api_base="http://model-help.test/v1",
        api_key="model-secret",
        completion=lambda **_: (_ for _ in ()).throw(TimeoutError("secret endpoint")),
    )

    with pytest.raises(ModelProviderUnavailable, match="unavailable") as error:
        provider.complete(_request())

    assert "secret endpoint" not in str(error.value)


def test_build_help_provider_requires_the_model_secret() -> None:
    with pytest.raises(ValueError, match="MODEL_API_KEY"):
        build_help_provider(
            {"RECLAIM_HELP_API_BASE": "http://model-help.test/v1"}
        )
