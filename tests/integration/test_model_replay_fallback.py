"""T077 provider-failure and deterministic replay fallback coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from agent.providers import (
    ModelCompletion,
    ModelProviderTimeout,
    ModelProviderUnavailable,
    ProviderMetadata,
)
from agent.tools import ToolCall
from agent.replay_fallback import (
    ReplayFallbackStatus,
    run_with_replay_fallback,
)
from packages.contracts.analysis_policy import (
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)

pytestmark = pytest.mark.integration


TENANT_ID = "tenant-t077"
CASE_ID = "case-t077"
CORRELATION_ID = "correlation-t077"


def request(mode: ProviderMode = ProviderMode.LIVE) -> ModelAnalysisRequest:
    return ModelAnalysisRequest(
        tenant_id=TENANT_ID,
        correlation_id=CORRELATION_ID,
        case_id=CASE_ID,
        redacted_case_representation={
            "evidence": [{"evidence_id": "evidence-t077"}],
            "timeline": [
                {
                    "timeline_event_id": "timeline-t077",
                    "evidence_references": ["evidence-t077"],
                }
            ],
            "uncertainty": ["timeline-t077:conflicting_sources"],
        },
        evidence_references=("evidence-t077",),
        policy_version_id="policy-t077",
        budget=ModelBudget(max_tokens=128),
        provider_mode=mode,
        replay_label=mode,
    )


def response(
    request_value: ModelAnalysisRequest,
    *,
    uncertainty: str = "review required: timeline-t077:conflicting_sources",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "analysis_id": "analysis-t077",
        "provider": "fixture-provider",
        "model": "fixture-model",
        "tenant_id": request_value.tenant_id,
        "case_id": request_value.case_id,
        "correlation_id": request_value.correlation_id,
        "attributions": [],
        "proposals": [],
        "uncertainty": uncertainty,
        "refusal_records": [],
    }


@dataclass
class FixtureProvider:
    mode: ProviderMode
    value: Any

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider="fixture-provider",
            model="fixture-model",
            mode=self.mode,
        )

    def complete(
        self, request: ModelAnalysisRequest, *, tool_results=()
    ) -> ModelCompletion:
        del tool_results
        if isinstance(self.value, BaseException):
            raise self.value
        return ModelCompletion(metadata=self.metadata, raw_output=self.value(request))


def replay_provider(value: Any = None):
    from agent.providers import ReplayProvider

    replay_value = (
        value if value is not None else response(request(ProviderMode.REPLAY))
    )
    if isinstance(replay_value, dict):
        replay_value = {
            **replay_value,
            "provider": "replay-fixture-t077",
            "model": "deterministic-fixture-t077",
        }
    return ReplayProvider(
        provider="replay-fixture-t077",
        model="deterministic-fixture-t077",
        response=replay_value,
    )


def test_live_provider_success_remains_live_and_side_effect_free() -> None:
    result = run_with_replay_fallback(
        request(),
        primary_provider=FixtureProvider(ProviderMode.LIVE, response),
        replay_provider=replay_provider(),
    )

    assert result.status is ReplayFallbackStatus.LIVE
    assert result.mode == "live"
    assert result.label == "live"
    assert result.analysis_response is not None
    assert result.primary_failure is None
    assert result.remote_side_effects == ()


@pytest.mark.parametrize(
    "failure",
    (
        ModelProviderTimeout("timeout"),
        ModelProviderUnavailable("unavailable"),
    ),
)
def test_provider_timeout_and_unavailability_use_labeled_replay(
    failure: Exception,
) -> None:
    result = run_with_replay_fallback(
        request(),
        primary_provider=FixtureProvider(ProviderMode.LIVE, failure),
        replay_provider=replay_provider(),
    )

    assert result.status is ReplayFallbackStatus.REPLAY
    assert result.mode == "replay"
    assert result.label == "replay"
    assert result.analysis_response is not None
    assert result.provenance["requested_mode"] == "live"
    assert result.provenance["effective_mode"] == "replay"
    assert (
        result.requested_request.redacted_case_representation
        == result.effective_request.redacted_case_representation
    )
    assert result.primary_failure in {
        "model provider timeout",
        "model provider unavailable",
    }
    assert result.remote_side_effects == ()


@pytest.mark.parametrize(
    "invalid_value",
    (
        "not-json",
        {"schema_version": "9.0.0"},
        {
            **response(request()),
            "attributions": [
                {
                    "timeline_event_id": "timeline-not-authoritative",
                    "label": "malicious",
                    "confidence": 1.0,
                    "rationale": "invalid reference",
                    "evidence_references": [],
                    "method": "fixture",
                    "model_or_rules_version": "fixture-v1",
                }
            ],
        },
        {**response(request()), "case_id": "case-other-t077"},
        {**response(request()), "uncertainty": "certain"},
    ),
)
def test_malformed_schema_reference_or_uncertainty_erasure_falls_back(
    invalid_value: Any,
) -> None:
    result = run_with_replay_fallback(
        request(),
        primary_provider=FixtureProvider(ProviderMode.LIVE, invalid_value),
        replay_provider=replay_provider(),
        deterministic_uncertainty=("timeline-t077:conflicting_sources",),
    )

    assert result.status is ReplayFallbackStatus.REPLAY
    assert result.analysis_response is not None
    assert "timeline-t077:conflicting_sources" in result.analysis_response.uncertainty
    assert result.primary_failure in {
        "model response JSON rejected",
        "model response schema rejected",
        "model provider response rejected",
        "model response failed strict validation",
    }


def test_replay_fixture_unavailable_is_explicit_escalation() -> None:
    result = run_with_replay_fallback(
        request(),
        primary_provider=FixtureProvider(
            ProviderMode.LIVE, ModelProviderUnavailable("provider unavailable")
        ),
        replay_provider=None,
    )

    assert result.status is ReplayFallbackStatus.ESCALATION
    assert result.analysis_response is None
    assert result.deterministic_only is True
    assert result.fallback_reason == "deterministic replay fixture is unavailable"
    assert result.remote_side_effects == ()


def test_forbidden_model_tool_attempt_is_recorded_and_never_executed() -> None:
    class ForbiddenToolProvider(FixtureProvider):
        def complete(
            self, request: ModelAnalysisRequest, *, tool_results=()
        ) -> ModelCompletion:
            del tool_results
            return ModelCompletion(
                metadata=self.metadata,
                raw_output=response(request),
                tool_calls=(ToolCall("forbidden-t077", "shell_command", {}),),
            )

    bounded_request = request().model_copy(
        update={"budget": ModelBudget(max_tokens=128, max_tool_calls=1)}
    )
    result = run_with_replay_fallback(
        bounded_request,
        primary_provider=ForbiddenToolProvider(ProviderMode.LIVE, response),
        replay_provider=replay_provider(),
    )

    assert result.status is ReplayFallbackStatus.REPLAY
    assert result.analysis_response is not None
    assert result.forbidden_attempts == ("shell_command",)
    assert result.remote_side_effects == ()


def test_corrupt_replay_fixture_is_explicit_escalation() -> None:
    result = run_with_replay_fallback(
        request(ProviderMode.REPLAY),
        replay_provider=replay_provider("corrupt-replay-fixture"),
        deterministic_uncertainty=("timeline-t077:conflicting_sources",),
    )

    assert result.status is ReplayFallbackStatus.ESCALATION
    assert result.analysis_response is None
    assert "replay rejected" in (result.fallback_reason or "")
    assert result.remote_side_effects == ()


def test_wrong_case_replay_fixture_is_rejected_before_completion() -> None:
    wrong_case = {
        **response(request(ProviderMode.REPLAY)),
        "case_id": "case-other-t077",
    }
    result = run_with_replay_fallback(
        request(),
        primary_provider=FixtureProvider(
            ProviderMode.LIVE, ModelProviderUnavailable("provider unavailable")
        ),
        replay_provider=replay_provider(wrong_case),
    )

    assert result.status is ReplayFallbackStatus.ESCALATION
    assert result.analysis_response is None
    assert result.deterministic_only is True
    assert "replay rejected" in (result.fallback_reason or "")
    assert result.remote_side_effects == ()


def test_replay_preserves_authoritative_uncertainty() -> None:
    replay_value = response(request(ProviderMode.REPLAY), uncertainty="certain")
    result = run_with_replay_fallback(
        request(),
        primary_provider=FixtureProvider(
            ProviderMode.LIVE, ModelProviderUnavailable("provider unavailable")
        ),
        replay_provider=replay_provider(replay_value),
        deterministic_uncertainty=("timeline-t077:conflicting_sources",),
    )

    assert result.status is ReplayFallbackStatus.ESCALATION
    assert result.analysis_response is None
    assert result.deterministic_only is True
