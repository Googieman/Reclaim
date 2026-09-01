"""Bounded provider failure handling for labeled deterministic replay.

This boundary is deliberately outside the provider adapters.  A live provider
failure never changes deterministic attribution or exposure and never becomes a
permission to broaden model capabilities.  If a replay artifact is unavailable
or invalid, the result is an explicit escalation/deterministic-only outcome.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from packages.contracts.analysis_policy import ModelAnalysisRequest, ProviderMode
from packages.contracts.common import CONTRACT_VERSION

from .langgraph_harness import LangGraphAnalysisHarness
from .output_parser import (
    AnalysisResponseError,
    ParsedAnalysisResponse,
    parse_validated_analysis_response,
)
from .providers import (
    ModelCompletion,
    ModelProvider,
    ModelProviderError,
    ModelProviderResponseError,
    ModelProviderTimeout,
    ModelProviderUnavailable,
)

REPLAY_FALLBACK_VERSION = "model-replay-fallback-v1.0.0"


class ReplayFallbackStatus(StrEnum):
    LIVE = "live"
    REPLAY = "replay"
    DETERMINISTIC_ONLY = "deterministic_only"
    ESCALATION = "escalation"


@dataclass(frozen=True, slots=True)
class ReplayFallbackOutcome:
    """The explicit result of a live attempt followed by replay fallback."""

    requested_request: ModelAnalysisRequest
    effective_request: ModelAnalysisRequest
    status: ReplayFallbackStatus
    response: ModelCompletion | None
    parsed_response: ParsedAnalysisResponse | None
    primary_failure: str | None = None
    fallback_reason: str | None = None
    failure_kind: str | None = None
    forbidden_attempts: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def mode(self) -> str:
        return self.effective_request.provider_mode.value

    @property
    def label(self) -> str:
        return self.effective_request.replay_label.value

    @property
    def analysis_response(self) -> Any | None:
        return self.parsed_response.response if self.parsed_response is not None else None

    @property
    def completed(self) -> bool:
        return self.status in {ReplayFallbackStatus.LIVE, ReplayFallbackStatus.REPLAY}

    @property
    def deterministic_only(self) -> bool:
        return self.status in {
            ReplayFallbackStatus.DETERMINISTIC_ONLY,
            ReplayFallbackStatus.ESCALATION,
        }

    @property
    def remote_side_effects(self) -> tuple[object, ...]:
        return ()


class ReplayFallback:
    """Try a provider once and then use one explicitly labeled replay provider."""

    def __init__(self, replay_provider: ModelProvider | None = None) -> None:
        if replay_provider is not None and not isinstance(replay_provider, ModelProvider):
            raise TypeError("replay fallback requires a provider-neutral replay adapter")
        self.replay_provider = replay_provider

    def run(
        self,
        request: ModelAnalysisRequest,
        *,
        primary_provider: ModelProvider | None = None,
        deterministic_uncertainty: tuple[str, ...] | list[str] = (),
    ) -> ReplayFallbackOutcome:
        _validate_request(request)
        uncertainty = tuple(deterministic_uncertainty)
        primary_failure: str | None = None
        primary_kind: str | None = None
        primary_forbidden_attempts: tuple[str, ...] = ()

        if request.provider_mode is ProviderMode.LIVE:
            if primary_provider is None:
                primary_failure = "live model provider is unavailable"
                primary_kind = "unavailable"
            else:
                try:
                    response, parsed = self._complete(
                        primary_provider,
                        request,
                        deterministic_uncertainty=uncertainty,
                    )
                    return self._success(
                        request=request,
                        effective_request=request,
                        status=ReplayFallbackStatus.LIVE,
                        response=response,
                        parsed=parsed,
                        primary_failure=None,
                        failure_kind=None,
                    )
                except _ProviderAttemptFailure as exc:
                    primary_failure = exc.safe_reason
                    primary_kind = exc.kind
                    primary_forbidden_attempts = exc.forbidden_attempts

        replay_request = _replay_request(request)
        if self.replay_provider is None:
            return self._failure(
                request=request,
                effective_request=replay_request,
                status=ReplayFallbackStatus.ESCALATION,
                primary_failure=primary_failure,
                fallback_reason="deterministic replay fixture is unavailable",
                failure_kind=primary_kind or "unavailable",
                forbidden_attempts=primary_forbidden_attempts,
            )
        try:
            response, parsed = self._complete(
                self.replay_provider,
                replay_request,
                deterministic_uncertainty=uncertainty,
            )
        except _ProviderAttemptFailure as exc:
            return self._failure(
                request=request,
                effective_request=replay_request,
                status=ReplayFallbackStatus.ESCALATION,
                primary_failure=primary_failure,
                fallback_reason=f"deterministic replay rejected: {exc.safe_reason}",
                failure_kind=exc.kind,
                forbidden_attempts=tuple(
                    sorted(set(primary_forbidden_attempts) | set(exc.forbidden_attempts))
                ),
            )
        return self._success(
            request=request,
            effective_request=replay_request,
            status=ReplayFallbackStatus.REPLAY,
            response=response,
            parsed=parsed,
            primary_failure=primary_failure,
            failure_kind=primary_kind,
            forbidden_attempts=primary_forbidden_attempts,
        )

    analyze = run
    run_analysis = run

    def _complete(
        self,
        provider: ModelProvider,
        request: ModelAnalysisRequest,
        *,
        deterministic_uncertainty: tuple[str, ...],
    ) -> tuple[ModelCompletion, ParsedAnalysisResponse]:
        try:
            harness_result = LangGraphAnalysisHarness(provider).run(request)
        except (
            ModelProviderError,
            ModelProviderResponseError,
            TimeoutError,
            ValueError,
            TypeError,
        ) as exc:
            raise _ProviderAttemptFailure(_safe_failure_reason(exc), _failure_kind(exc)) from exc
        if harness_result.status != "completed" or harness_result.provider_response is None:
            raise _ProviderAttemptFailure(
                _safe_harness_failure(harness_result.error),
                _failure_kind_from_text(harness_result.error),
                harness_result.forbidden_attempts,
            )
        try:
            parsed = parse_validated_analysis_response(
                harness_result.provider_response,
                request,
                deterministic_uncertainty=deterministic_uncertainty,
            )
        except (AnalysisResponseError, ValueError, TypeError) as exc:
            raise _ProviderAttemptFailure(_safe_failure_reason(exc), "invalid_response") from exc
        return harness_result.provider_response, parsed

    def _success(
        self,
        *,
        request: ModelAnalysisRequest,
        effective_request: ModelAnalysisRequest,
        status: ReplayFallbackStatus,
        response: ModelCompletion,
        parsed: ParsedAnalysisResponse,
        primary_failure: str | None,
        failure_kind: str | None,
        forbidden_attempts: tuple[str, ...] = (),
    ) -> ReplayFallbackOutcome:
        metadata = response.metadata
        provenance = {
            "fallback_version": REPLAY_FALLBACK_VERSION,
            "requested_mode": request.provider_mode.value,
            "effective_mode": effective_request.provider_mode.value,
            "label": effective_request.replay_label.value,
            "provider": metadata.provider,
            "model": metadata.model,
            "adapter_version": metadata.adapter_version,
            "request_schema_version": effective_request.schema_version,
            "response_schema_version": metadata.response_schema_version,
            "request_checksum": _checksum(effective_request.model_dump(mode="json")),
            "response_checksum": parsed.provenance.response_checksum,
            "primary_failure": primary_failure,
            "failure_kind": failure_kind,
            "side_effects": False,
        }
        return ReplayFallbackOutcome(
            requested_request=request,
            effective_request=effective_request,
            status=status,
            response=response,
            parsed_response=parsed,
            primary_failure=primary_failure,
            failure_kind=failure_kind,
            forbidden_attempts=tuple(sorted(set(forbidden_attempts))),
            provenance=provenance,
        )

    def _failure(
        self,
        *,
        request: ModelAnalysisRequest,
        effective_request: ModelAnalysisRequest,
        status: ReplayFallbackStatus,
        primary_failure: str | None,
        fallback_reason: str,
        failure_kind: str,
        forbidden_attempts: tuple[str, ...] = (),
    ) -> ReplayFallbackOutcome:
        provenance = {
            "fallback_version": REPLAY_FALLBACK_VERSION,
            "requested_mode": request.provider_mode.value,
            "effective_mode": effective_request.provider_mode.value,
            "label": effective_request.replay_label.value,
            "request_checksum": _checksum(effective_request.model_dump(mode="json")),
            "primary_failure": primary_failure,
            "fallback_reason": fallback_reason,
            "failure_kind": failure_kind,
            "side_effects": False,
        }
        return ReplayFallbackOutcome(
            requested_request=request,
            effective_request=effective_request,
            status=status,
            response=None,
            parsed_response=None,
            primary_failure=primary_failure,
            fallback_reason=fallback_reason,
            failure_kind=failure_kind,
            forbidden_attempts=tuple(sorted(set(forbidden_attempts))),
            provenance=provenance,
        )


def run_with_replay_fallback(
    request: ModelAnalysisRequest,
    *,
    primary_provider: ModelProvider | None = None,
    replay_provider: ModelProvider | None = None,
    deterministic_uncertainty: tuple[str, ...] | list[str] = (),
) -> ReplayFallbackOutcome:
    """Functional T077 entry point."""

    return ReplayFallback(replay_provider).run(
        request,
        primary_provider=primary_provider,
        deterministic_uncertainty=deterministic_uncertainty,
    )


DeterministicReplayFallback = ReplayFallback
ReplayFallbackRunner = ReplayFallback


class _ProviderAttemptFailure(RuntimeError):
    def __init__(
        self,
        safe_reason: str,
        kind: str,
        forbidden_attempts: tuple[str, ...] = (),
    ) -> None:
        super().__init__(safe_reason)
        self.safe_reason = safe_reason
        self.kind = kind
        self.forbidden_attempts = tuple(forbidden_attempts)


def _replay_request(request: ModelAnalysisRequest) -> ModelAnalysisRequest:
    if request.provider_mode is ProviderMode.REPLAY and request.replay_label is ProviderMode.REPLAY:
        return request
    return request.model_copy(
        update={"provider_mode": ProviderMode.REPLAY, "replay_label": ProviderMode.REPLAY}
    )


def _validate_request(request: ModelAnalysisRequest) -> None:
    if not isinstance(request, ModelAnalysisRequest):
        raise TypeError("replay fallback requires a typed analysis request")
    if request.schema_version != CONTRACT_VERSION:
        raise ValueError("analysis request schema version is unsupported")
    if request.provider_mode is not request.replay_label:
        raise ValueError("analysis request mode and replay label do not match")


def _safe_failure_reason(exc: Exception) -> str:
    if isinstance(exc, ModelProviderTimeout) or isinstance(exc, TimeoutError):
        return "model provider timeout"
    if isinstance(exc, ModelProviderUnavailable):
        return "model provider unavailable"
    if isinstance(exc, ModelProviderResponseError):
        return "model provider response envelope rejected"
    if isinstance(exc, AnalysisResponseError):
        return "model response failed strict validation"
    return "model provider attempt failed"


def _safe_harness_failure(error: str | None) -> str:
    if error == "model provider timeout":
        return error
    if error == "model provider unavailable":
        return error
    if error == "model provider failure":
        return error
    if error and "schema" in error.lower():
        return "model response schema rejected"
    if error and "json" in error.lower():
        return "model response JSON rejected"
    return "model provider response rejected"


def _failure_kind(exc: Exception) -> str:
    if isinstance(exc, ModelProviderTimeout | TimeoutError):
        return "timeout"
    if isinstance(exc, ModelProviderUnavailable):
        return "unavailable"
    if isinstance(exc, ModelProviderResponseError | AnalysisResponseError | ValueError | TypeError):
        return "invalid_response"
    return "provider_failure"


def _failure_kind_from_text(value: str | None) -> str:
    if value and "timeout" in value:
        return "timeout"
    if value and "failure" in value:
        return "provider_failure"
    return "invalid_response"


def _checksum(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "DETERMINISTIC_REPLAY_FALLBACK",
    "DeterministicReplayFallback",
    "REPLAY_FALLBACK_VERSION",
    "ReplayFallback",
    "ReplayFallbackOutcome",
    "ReplayFallbackRunner",
    "ReplayFallbackStatus",
    "run_with_replay_fallback",
]


DETERMINISTIC_REPLAY_FALLBACK = ReplayFallback
