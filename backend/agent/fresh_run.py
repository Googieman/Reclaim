"""A real, explicitly fresh RECLAIM model-analysis execution boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from packages.contracts.analysis_policy import ModelAnalysisRequest, ProviderMode

from .langgraph_harness import HARNESS_VERSION, LangGraphAnalysisHarness
from .output_parser import (
    OUTPUT_PARSER_VERSION,
    AnalysisResponseError,
    ParsedAnalysisResponse,
    parse_validated_analysis_response,
)
from .prompts import PROMPT_VERSION
from .providers import (
    ModelCompletion,
    ModelProvider,
    ModelProviderError,
    ModelProviderTimeout,
    ModelProviderUnavailable,
)

FRESH_AGENT_VERSION = "fresh-agent-runtime-v1.0.0"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    REJECTED = "rejected"
    DETERMINISTIC_ONLY = "deterministic_only"
    ESCALATION_REQUIRED = "escalation_required"


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Safe public result for one fresh model attempt.

    Raw provider output is intentionally not retained here. Parsed advisory output
    is still not execution authority; policy and Action Gateway remain downstream.
    """

    run_id: str
    request: ModelAnalysisRequest
    status: AgentRunStatus
    execution_mode: str = "fresh_agent"
    action_environment: str = "simulator"
    profile: str = "reclaim-specialist"
    provider: str | None = None
    model: str | None = None
    analysis_response: Any | None = None
    proposal_validation: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    request_checksum: str = ""
    response_checksum: str | None = None
    token_count: int | None = None
    estimated_cost: Any | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempted_providers: tuple[dict[str, str], ...] = ()
    prompt_version: str = PROMPT_VERSION
    harness_version: str = HARNESS_VERSION
    parser_version: str = OUTPUT_PARSER_VERSION
    runtime_version: str = FRESH_AGENT_VERSION

    def __post_init__(self) -> None:
        if self.execution_mode != "fresh_agent":
            raise ValueError("AgentRun is only for fresh_agent execution")
        if self.request.provider_mode is not ProviderMode.LIVE:
            raise ValueError("fresh agent requests must use the live provider mode")
        if self.request.replay_label is not ProviderMode.LIVE:
            raise ValueError("fresh agent requests cannot carry a replay label")
        if self.status is AgentRunStatus.COMPLETED and self.analysis_response is None:
            raise ValueError("completed fresh agent runs require parsed analysis")
        if self.status is not AgentRunStatus.COMPLETED and self.analysis_response is not None:
            raise ValueError("non-completed fresh agent runs cannot expose analysis")
        object.__setattr__(self, "proposal_validation", dict(self.proposal_validation))
        object.__setattr__(
            self, "attempted_providers", tuple(dict(item) for item in self.attempted_providers)
        )

    @property
    def fresh_execution_observed(self) -> bool:
        return bool(self.attempted_providers)

    @property
    def analysis_id(self) -> str | None:
        return getattr(self.analysis_response, "analysis_id", None)

    def to_dict(self) -> dict[str, Any]:
        """Serialize only redacted, operationally useful provenance."""

        analysis = None
        if self.analysis_response is not None:
            analysis = self.analysis_response.model_dump(mode="json")
        return {
            "run_id": self.run_id,
            "tenant_id": self.request.tenant_id,
            "case_id": self.request.case_id,
            "correlation_id": self.request.correlation_id,
            "execution_mode": self.execution_mode,
            "provider_mode": self.request.provider_mode.value,
            "action_environment": self.action_environment,
            "profile": self.profile,
            "provider": self.provider,
            "model": self.model,
            "status": self.status.value,
            "analysis": analysis,
            "proposal_validation": dict(self.proposal_validation),
            "policy_result": None,
            "error": self.error,
            "provenance": {
                "prompt_version": self.prompt_version,
                "harness_version": self.harness_version,
                "parser_version": self.parser_version,
                "runtime_version": self.runtime_version,
                "request_checksum": self.request_checksum,
                "response_checksum": self.response_checksum,
                "token_count": self.token_count,
                "estimated_cost": _jsonable(self.estimated_cost),
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "finished_at": self.finished_at.isoformat() if self.finished_at else None,
                "fresh_execution_observed": self.fresh_execution_observed,
                "attempted_providers": [dict(item) for item in self.attempted_providers],
            },
            "remote_side_effects": [],
        }


class FreshAgentCoordinator:
    """Run one bounded live-provider request without replay substitution."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        profile: str = "reclaim-specialist",
        fallback_provider: ModelProvider | None = None,
        fallback_profile: str | None = None,
        action_environment: str = "simulator",
    ) -> None:
        if not isinstance(provider, ModelProvider):
            raise TypeError("fresh agent requires a provider-neutral model adapter")
        if fallback_provider is not None and not isinstance(fallback_provider, ModelProvider):
            raise TypeError("fresh agent fallback requires a provider-neutral model adapter")
        if fallback_provider is not None and not fallback_profile:
            raise ValueError("fresh agent fallback profile is required")
        if action_environment not in {"simulator", "test_mode", "live_merchant"}:
            raise ValueError("action environment is unsupported")
        self.provider = provider
        self.profile = profile
        self.fallback_provider = fallback_provider
        self.fallback_profile = fallback_profile
        self.action_environment = action_environment

    def run(
        self,
        request: ModelAnalysisRequest,
        *,
        deterministic_uncertainty: tuple[str, ...] | list[str] = (),
    ) -> AgentRun:
        _validate_request(request)
        started = datetime.now(UTC)
        request_checksum = _checksum(request.model_dump(mode="json"))
        attempts: list[dict[str, str]] = []
        providers: list[tuple[str, ModelProvider]] = [(self.profile, self.provider)]
        if self.fallback_provider is not None:
            providers.append(
                (self.fallback_profile or "configured-fallback", self.fallback_provider)
            )

        last_status = AgentRunStatus.UNAVAILABLE
        last_error: str | None = None
        for profile, provider in providers:
            attempts.append(
                {
                    "profile": profile,
                    "provider": provider.metadata.provider,
                    "model": provider.metadata.model,
                }
            )
            result, status, error = self._attempt(
                request,
                provider,
                deterministic_uncertainty=tuple(deterministic_uncertainty),
            )
            if result is not None:
                parsed, completion = result
                finished = datetime.now(UTC)
                return AgentRun(
                    run_id=_run_id(),
                    request=request,
                    status=AgentRunStatus.COMPLETED,
                    action_environment=self.action_environment,
                    profile=profile,
                    provider=completion.metadata.provider,
                    model=completion.metadata.model,
                    analysis_response=parsed.response,
                    proposal_validation={
                        "status": "accepted",
                        "validation_scope": "advisory_typed_boundary",
                        "side_effects": False,
                    },
                    request_checksum=request_checksum,
                    response_checksum=parsed.provenance.response_checksum,
                    token_count=parsed.provenance.token_count,
                    estimated_cost=parsed.provenance.estimated_cost,
                    started_at=started,
                    finished_at=finished,
                    attempted_providers=tuple(attempts),
                )
            last_status, last_error = status, error

        finished = datetime.now(UTC)
        return AgentRun(
            run_id=_run_id(),
            request=request,
            status=last_status,
            action_environment=self.action_environment,
            profile=self.profile,
            provider=attempts[-1]["provider"] if attempts else None,
            model=attempts[-1]["model"] if attempts else None,
            error=last_error,
            request_checksum=request_checksum,
            started_at=started,
            finished_at=finished,
            attempted_providers=tuple(attempts),
        )

    analyze = run

    @staticmethod
    def _attempt(
        request: ModelAnalysisRequest,
        provider: ModelProvider,
        *,
        deterministic_uncertainty: tuple[str, ...],
    ) -> tuple[tuple[ParsedAnalysisResponse, ModelCompletion] | None, AgentRunStatus, str | None]:
        try:
            harness_result = LangGraphAnalysisHarness(provider).run(request)
        except (ModelProviderTimeout, TimeoutError):
            return None, AgentRunStatus.UNAVAILABLE, "model provider timeout"
        except ModelProviderUnavailable:
            return None, AgentRunStatus.UNAVAILABLE, "model provider unavailable"
        except ModelProviderError:
            return None, AgentRunStatus.FAILED, "model provider failure"
        except (ValueError, TypeError) as exc:
            return None, AgentRunStatus.REJECTED, _safe_error(exc)

        if harness_result.status != "completed" or harness_result.provider_response is None:
            status = (
                AgentRunStatus.REJECTED
                if harness_result.status == "rejected"
                or any(
                    checkpoint.stage in {"output_rejected", "tool_rejected", "tool_budget_rejected"}
                    for checkpoint in harness_result.checkpoints
                )
                else _status_from_error(harness_result.error)
            )
            return None, status, _safe_text(harness_result.error or "model analysis failed")

        try:
            parsed = parse_validated_analysis_response(
                harness_result.provider_response,
                request,
                deterministic_uncertainty=deterministic_uncertainty,
            )
        except AnalysisResponseError as exc:
            return None, AgentRunStatus.REJECTED, _safe_error(exc)
        return (parsed, harness_result.provider_response), AgentRunStatus.COMPLETED, None


def run_fresh_agent(
    request: ModelAnalysisRequest,
    provider: ModelProvider,
    *,
    profile: str = "reclaim-specialist",
    fallback_provider: ModelProvider | None = None,
    fallback_profile: str | None = None,
    action_environment: str = "simulator",
    deterministic_uncertainty: tuple[str, ...] | list[str] = (),
) -> AgentRun:
    return FreshAgentCoordinator(
        provider,
        profile=profile,
        fallback_provider=fallback_provider,
        fallback_profile=fallback_profile,
        action_environment=action_environment,
    ).run(request, deterministic_uncertainty=deterministic_uncertainty)


def _validate_request(request: ModelAnalysisRequest) -> None:
    if not isinstance(request, ModelAnalysisRequest):
        raise TypeError("fresh agent requires a typed analysis request")
    if (
        request.provider_mode is not ProviderMode.LIVE
        or request.replay_label is not ProviderMode.LIVE
    ):
        raise ValueError("fresh agent requires a live-labelled provider request")


def _status_from_error(error: str | None) -> AgentRunStatus:
    text = (error or "").lower()
    if "unavailable" in text or "timeout" in text:
        return AgentRunStatus.UNAVAILABLE
    return AgentRunStatus.FAILED


def _safe_error(error: BaseException) -> str:
    return _safe_text(str(error))


def _safe_text(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) > 240:
        return normalized[:237] + "..."
    return normalized or "fresh agent run failed"


def _run_id() -> str:
    return "agent-run:" + uuid4().hex


def _checksum(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


__all__ = [
    "AgentRun",
    "AgentRunStatus",
    "FRESH_AGENT_VERSION",
    "FreshAgentCoordinator",
    "run_fresh_agent",
]
