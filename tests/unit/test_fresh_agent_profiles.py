"""Logical model profile resolution is allowlisted and credential-safe."""

from __future__ import annotations

import pytest
from agent.model_profiles import (
    ModelProfileError,
    ModelProfileUnavailable,
    build_provider,
    resolve_profile,
)


def test_specialist_requires_an_explicit_local_model() -> None:
    with pytest.raises(ModelProfileUnavailable, match="RECLAIM_SPECIALIST_MODEL"):
        resolve_profile("reclaim-specialist", environ={})


def test_baseline_profile_has_a_safe_default_and_endpoint_cannot_embed_credentials() -> (
    None
):
    profile = resolve_profile("reclaim-baseline", environ={})
    assert profile.model == "HuggingFaceTB/SmolLM2-135M-Instruct"
    with pytest.raises(ModelProfileError, match="credentials"):
        resolve_profile(
            "reclaim-specialist",
            environ={
                "RECLAIM_SPECIALIST_MODEL": "local-model",
                "RECLAIM_SPECIALIST_API_BASE": "https://user:password@example.invalid/v1",
            },
        )


def test_cloud_fallback_requires_explicit_key_name_and_hides_key_from_provider_metadata() -> (
    None
):
    profile = resolve_profile(
        "reclaim-cloud-fallback",
        environ={
            "RECLAIM_CLOUD_PROVIDER": "openai",
            "RECLAIM_CLOUD_MODEL": "gpt-test",
            "RECLAIM_CLOUD_API_KEY_ENV": "TEST_CLOUD_KEY",
            "TEST_CLOUD_KEY": "secret-value",
        },
    )
    provider = build_provider(profile)
    assert provider.metadata.provider == "openai"
    assert provider.metadata.model == "gpt-test"
    assert "secret-value" not in repr(provider.metadata)


def test_specialist_fallback_cycle_is_rejected() -> None:
    with pytest.raises(ModelProfileError, match="cycle"):
        resolve_profile(
            "reclaim-specialist",
            environ={
                "RECLAIM_SPECIALIST_MODEL": "local-model",
                "RECLAIM_AGENT_FALLBACK_PROFILE": "reclaim-specialist",
            },
        )


def test_help_profile_is_separate_and_disabled_by_default() -> None:
    profile = resolve_profile("reclaim-help-deepseek", environ={})

    assert profile.name == "reclaim-help-deepseek"
    assert profile.model == "deepseek-r1-distill-qwen-1.5b-q4_0.gguf"
    assert profile.api_base == "http://model-help:8080/v1"
    assert profile.enabled is False
