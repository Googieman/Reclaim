"""LiteLLM adapter isolated behind the provider-neutral model boundary."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from packages.contracts.analysis_policy import ModelAnalysisRequest, ProviderMode
from packages.contracts.common import CONTRACT_VERSION

from .prompts import bounded_context_json, build_system_prompt
from .providers import (
    ModelCompletion,
    ModelProvider,
    ModelProviderResponseError,
    ModelProviderTimeout,
    ModelProviderUnavailable,
    ProviderMetadata,
    ProviderProfile,
    ProviderRouter,
)
from .redaction import redact_value
from .tools import ToolCall, ToolResult

LITELLM_GATEWAY_VERSION = "litellm-gateway-v1.0.0"

CompletionFunction = Callable[..., Any]


class LiteLLMProviderAdapter:
    """Translate the common request into a LiteLLM call without leaking vendor types."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        mode: ProviderMode = ProviderMode.LIVE,
        completion: CompletionFunction | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
        transport_model: str | None = None,
    ) -> None:
        self.profile = ProviderProfile(provider, model, mode, LITELLM_GATEWAY_VERSION)
        self._metadata = ProviderMetadata(
            provider=provider,
            model=model,
            mode=mode,
            adapter_version=LITELLM_GATEWAY_VERSION,
        )
        self._completion = completion
        self._api_base = api_base
        self._api_key = api_key
        self._transport_model = transport_model or model

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    def complete(
        self,
        request: ModelAnalysisRequest,
        *,
        tool_results: Sequence[ToolResult] = (),
    ) -> ModelCompletion:
        _validate_request(request, self.profile.mode)
        payload = build_model_input(request, tool_results=tool_results)
        completion = self._completion or _default_completion
        try:
            transport = dict(payload)
            if self._api_base:
                transport["api_base"] = self._api_base
            if self._api_key:
                # This value is used only by the transport adapter and never enters
                # the request messages, model context, or returned provenance.
                transport["api_key"] = self._api_key
            elif self._api_base and self._transport_model.startswith("openai/"):
                # LiteLLM requires an OpenAI-compatible key-shaped value even for
                # loopback servers that do not authenticate. This is a sentinel,
                # not a credential, and is transport-only.
                transport["api_key"] = "sk-reclaim-local"
            response = completion(model=self._transport_model, **transport)
        except TimeoutError as exc:
            raise ModelProviderTimeout("model provider timed out") from exc
        except ModelProviderUnavailable:
            raise
        except Exception as exc:
            raise ModelProviderUnavailable("model provider is unavailable") from exc
        return _coerce_response(response, self._metadata)


class LiteLLMGateway:
    """Route typed requests to interchangeable adapters."""

    def __init__(self, providers: Mapping[str, ModelProvider] | None = None) -> None:
        self._router = ProviderRouter(providers)

    def register(self, provider_key: str, provider: ModelProvider) -> None:
        self._router.register(provider_key, provider)

    def providers(self) -> tuple[str, ...]:
        return self._router.names()

    def complete(
        self,
        request: ModelAnalysisRequest,
        *,
        provider_key: str,
        tool_results: Sequence[ToolResult] = (),
    ) -> ModelCompletion:
        return self._router.complete(
            request,
            provider_key=provider_key,
            tool_results=tool_results,
        )


ProviderNeutralModelGateway = LiteLLMGateway
LiteLLMGatewayAdapter = LiteLLMProviderAdapter


def build_model_input(
    request: ModelAnalysisRequest,
    *,
    tool_results: Sequence[ToolResult] = (),
) -> dict[str, Any]:
    """Build the identical, credential-free payload supplied to every provider."""

    if not isinstance(request, ModelAnalysisRequest):
        raise ModelProviderResponseError("model gateway requires a typed analysis request")
    if request.schema_version != CONTRACT_VERSION:
        raise ModelProviderResponseError("unsupported analysis request schema version")
    safe_request = redact_value(request.model_dump(mode="json"))
    safe_context = safe_request.get("redacted_case_representation", {})
    # Fail closed before a provider call if a caller attempts to bypass the
    # bounded context serializer.
    bounded_context_json(safe_context)
    safe_results = [
        redact_value(
            {
                "schema_version": result.schema_version,
                "call_id": result.call_id,
                "name": result.name,
                "tenant_id": result.tenant_id,
                "case_id": result.case_id,
                "ok": result.ok,
                "output": result.output,
                "error": result.error,
            }
        )
        for result in tool_results
    ]
    request_json = json.dumps(safe_request, sort_keys=True, separators=(",", ":"))
    results_json = json.dumps(safe_results, sort_keys=True, separators=(",", ":"))
    return {
        "messages": [
            {
                "role": "system",
                "content": (build_system_prompt()),
            },
            {
                "role": "user",
                "content": request_json,
            },
            *(
                [
                    {
                        "role": "tool",
                        "content": results_json,
                    }
                ]
                if safe_results
                else []
            ),
        ],
        "max_tokens": request.budget.max_tokens,
        "timeout": request.budget.timeout_seconds,
    }


def _default_completion(*, model: str, **payload: Any) -> Any:
    try:
        import litellm
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ModelProviderUnavailable("LiteLLM is not installed") from exc
    # The provider/model selection is transport configuration, never an
    # arbitrary request field.  LiteLLM's vendor-specific response is converted
    # immediately to ModelCompletion below.
    return litellm.completion(model=model, **payload)


def _validate_request(request: ModelAnalysisRequest, mode: ProviderMode) -> None:
    if not isinstance(request, ModelAnalysisRequest):
        raise ModelProviderResponseError("model gateway requires a typed analysis request")
    if request.schema_version != CONTRACT_VERSION:
        raise ModelProviderResponseError("unsupported analysis request schema version")
    if request.provider_mode is not mode or request.replay_label is not mode:
        raise ModelProviderResponseError("request mode does not match provider adapter")


def _coerce_response(value: Any, metadata: ProviderMetadata) -> ModelCompletion:
    choices = _get(value, "choices")
    if not isinstance(choices, Sequence) or isinstance(choices, str | bytes) or not choices:
        raise ModelProviderResponseError("provider response choices are missing")
    first = choices[0]
    message = _get(first, "message")
    if not isinstance(message, Mapping) and message is None:
        raise ModelProviderResponseError("provider response message is missing")
    content = _get(message, "content")
    raw_tool_calls = _get(message, "tool_calls", ())
    if content is None and not raw_tool_calls:
        raise ModelProviderResponseError("provider response has no content or tool calls")
    tool_calls = _tool_calls(raw_tool_calls)
    usage = _get(value, "usage")
    token_count = _get(usage, "total_tokens") if usage is not None else None
    cost = _get(value, "response_cost")
    if cost is None:
        hidden = _get(value, "_hidden_params")
        cost = _get(hidden, "response_cost")
    return ModelCompletion(
        metadata=metadata,
        raw_output=content,
        tool_calls=tool_calls,
        token_count=token_count,
        estimated_cost=cost,
    )


def _tool_calls(value: Any) -> tuple[ToolCall, ...]:
    if value in (None, ()):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ModelProviderResponseError("provider tool calls must be a sequence")
    calls: list[ToolCall] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping) and raw is None:
            raise ModelProviderResponseError(f"provider tool call {index} is malformed")
        function = _get(raw, "function") or raw
        name = _get(function, "name")
        arguments = _get(function, "arguments", {})
        call_id = _get(raw, "id", f"tool-call-{index}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ModelProviderResponseError(
                    f"provider tool call {index} arguments are not JSON"
                ) from exc
        if not isinstance(arguments, Mapping):
            raise ModelProviderResponseError(
                f"provider tool call {index} arguments must be an object"
            )
        try:
            calls.append(ToolCall(call_id=str(call_id), name=str(name), arguments=arguments))
        except (TypeError, ValueError) as exc:
            raise ModelProviderResponseError(f"provider tool call {index} is invalid") from exc
    return tuple(calls)


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    if value is None:
        return default
    return getattr(value, name, default)


__all__ = [
    "LITELLM_GATEWAY_VERSION",
    "LiteLLMGateway",
    "LiteLLMGatewayAdapter",
    "LiteLLMProviderAdapter",
    "ProviderNeutralModelGateway",
    "build_model_input",
]
