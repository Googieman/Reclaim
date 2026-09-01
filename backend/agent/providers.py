"""Provider-neutral model adapter contracts and deterministic replay providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from packages.contracts.analysis_policy import ModelAnalysisRequest, ProviderMode
from packages.contracts.common import CONTRACT_VERSION

from .tools import ToolCall, ToolResult

PROVIDER_ADAPTER_VERSION = "provider-adapter-v1.0.0"


class ModelProviderError(RuntimeError):
    """Base error for a provider boundary failure."""


class ModelProviderUnavailable(ModelProviderError):
    """The provider could not produce a response."""


class ModelProviderTimeout(ModelProviderUnavailable):
    """The provider exceeded the request timeout."""


class ModelProviderResponseError(ModelProviderError):
    """The provider response envelope is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Stable provider/model selection metadata, independent of vendor semantics."""

    provider: str
    model: str
    mode: ProviderMode
    adapter_version: str = PROVIDER_ADAPTER_VERSION

    def __post_init__(self) -> None:
        for name in ("provider", "model", "adapter_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"provider profile {name} is required")
        if not isinstance(self.mode, ProviderMode):
            object.__setattr__(self, "mode", ProviderMode(self.mode))


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Metadata captured alongside an untrusted model response."""

    provider: str
    model: str
    mode: ProviderMode
    request_schema_version: str = CONTRACT_VERSION
    response_schema_version: str = CONTRACT_VERSION
    adapter_version: str = PROVIDER_ADAPTER_VERSION

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "model",
            "request_schema_version",
            "response_schema_version",
            "adapter_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"provider metadata {name} is required")
        if not isinstance(self.mode, ProviderMode):
            object.__setattr__(self, "mode", ProviderMode(self.mode))


@dataclass(frozen=True, slots=True)
class ModelCompletion:
    """Provider-neutral response envelope; its payload remains untrusted."""

    metadata: ProviderMetadata
    raw_output: Any
    tool_calls: tuple[ToolCall, ...] = ()
    token_count: int | None = None
    estimated_cost: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ProviderMetadata):
            raise ModelProviderResponseError("provider metadata is required")
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        call_ids = [call.call_id for call in self.tool_calls]
        if len(set(call_ids)) != len(call_ids):
            raise ModelProviderResponseError("provider returned duplicate tool call identities")
        if self.token_count is not None and (
            isinstance(self.token_count, bool)
            or not isinstance(self.token_count, int)
            or self.token_count < 0
        ):
            raise ModelProviderResponseError("provider token count is invalid")
        if self.estimated_cost is not None and self.estimated_cost < 0:
            raise ModelProviderResponseError("provider cost is invalid")


@runtime_checkable
class ModelProvider(Protocol):
    """The only interface consumed by the analysis graph."""

    @property
    def metadata(self) -> ProviderMetadata: ...

    def complete(
        self,
        request: ModelAnalysisRequest,
        *,
        tool_results: Sequence[ToolResult] = (),
    ) -> ModelCompletion: ...


ModelAdapter = ModelProvider
ProviderAdapter = ModelProvider
ReplayFactory = Callable[[ModelAnalysisRequest, tuple[ToolResult, ...]], ModelCompletion]


class ReplayProvider:
    """Deterministic provider used for replay and tests without hosted credentials."""

    def __init__(
        self,
        *,
        provider: str = "replay-fixture",
        model: str = "deterministic-boundary",
        response: ModelCompletion | Any | None = None,
        response_factory: ReplayFactory | None = None,
    ) -> None:
        if response is None and response_factory is None:
            raise ValueError("replay provider requires a response or response factory")
        if response is not None and response_factory is not None:
            raise ValueError("replay provider accepts one response source")
        self._profile = ProviderProfile(provider, model, ProviderMode.REPLAY)
        self._metadata = _metadata(self._profile)
        self._response = response
        self._response_factory = response_factory

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    def complete(
        self,
        request: ModelAnalysisRequest,
        *,
        tool_results: Sequence[ToolResult] = (),
    ) -> ModelCompletion:
        _validate_request_mode(request, ProviderMode.REPLAY)
        results = tuple(tool_results)
        value = (
            self._response_factory(request, results)
            if self._response_factory is not None
            else self._response
        )
        if isinstance(value, ModelCompletion):
            if value.metadata != self.metadata:
                raise ModelProviderResponseError("replay response metadata does not match provider")
            return value
        return ModelCompletion(metadata=self.metadata, raw_output=value)


StaticReplayProvider = ReplayProvider
DeterministicReplayProvider = ReplayProvider


class ProviderRouter:
    """Select interchangeable adapters without exposing provider-specific types."""

    def __init__(self, providers: Mapping[str, ModelProvider] | None = None) -> None:
        self._providers: dict[str, ModelProvider] = {}
        for key, provider in (providers or {}).items():
            self.register(key, provider)

    def register(self, key: str, provider: ModelProvider) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("provider key is required")
        if key in self._providers:
            raise ValueError(f"provider key already registered: {key}")
        if not isinstance(provider, ModelProvider):
            raise TypeError("provider does not implement the model adapter interface")
        self._providers[key] = provider

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def resolve(self, key: str) -> ModelProvider:
        try:
            return self._providers[key]
        except KeyError as exc:
            raise ModelProviderUnavailable(f"model provider is not configured: {key}") from exc

    def complete(
        self,
        request: ModelAnalysisRequest,
        *,
        provider_key: str,
        tool_results: Sequence[ToolResult] = (),
    ) -> ModelCompletion:
        return self.resolve(provider_key).complete(request, tool_results=tool_results)


def _metadata(profile: ProviderProfile) -> ProviderMetadata:
    return ProviderMetadata(
        provider=profile.provider,
        model=profile.model,
        mode=profile.mode,
        adapter_version=profile.adapter_version,
    )


def _validate_request_mode(request: ModelAnalysisRequest, mode: ProviderMode) -> None:
    if not isinstance(request, ModelAnalysisRequest):
        raise ModelProviderResponseError("model provider requires a typed analysis request")
    if request.schema_version != CONTRACT_VERSION:
        raise ModelProviderResponseError("unsupported analysis request schema version")
    if request.provider_mode is not mode or request.replay_label is not mode:
        raise ModelProviderResponseError("provider mode and replay label do not match adapter")


__all__ = [
    "DeterministicReplayProvider",
    "ModelAdapter",
    "ModelCompletion",
    "ModelProvider",
    "ModelProviderError",
    "ModelProviderResponseError",
    "ModelProviderTimeout",
    "ModelProviderUnavailable",
    "PROVIDER_ADAPTER_VERSION",
    "ProviderAdapter",
    "ProviderMetadata",
    "ProviderProfile",
    "ProviderRouter",
    "ReplayProvider",
    "StaticReplayProvider",
]
