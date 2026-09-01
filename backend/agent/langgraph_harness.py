"""Finite LangGraph harness for advisory, side-effect-free analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from packages.contracts.analysis_policy import ActionType, AttributionLabel, ModelAnalysisRequest
from packages.contracts.common import CONTRACT_VERSION

from .providers import (
    ModelCompletion,
    ModelProvider,
    ModelProviderError,
    ModelProviderTimeout,
    ProviderMetadata,
)
from .redaction import redact_value
from .tool_registry import build_tool_registry
from .tools import (
    ToolBoundaryError,
    ToolContext,
    ToolRegistry,
    ToolResult,
)

HARNESS_VERSION = "langgraph-harness-v1.0.0"


class AnalysisHarnessError(RuntimeError):
    """The bounded analysis boundary rejected or could not complete a run."""


class AnalysisRequestError(AnalysisHarnessError):
    """The typed request is stale, malformed, or outside the harness boundary."""


class AnalysisOutputError(AnalysisHarnessError):
    """The provider returned an unsupported output envelope."""


@dataclass(frozen=True, slots=True)
class AnalysisCheckpoint:
    """Typed, redacted progress evidence emitted at each graph boundary."""

    stage: str
    request_checksum: str
    mode: str
    provider: str | None = None
    model: str | None = None
    tool_call_count: int = 0
    status: str = "running"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BoundedAnalysisResult:
    """Advisory result; provider output remains untrusted and non-authoritative."""

    request: ModelAnalysisRequest
    status: Literal["completed", "rejected", "failed"]
    provider_response: ModelCompletion | None
    checkpoints: tuple[AnalysisCheckpoint, ...]
    tool_results: tuple[ToolResult, ...] = ()
    forbidden_attempts: tuple[str, ...] = ()
    error: str | None = None
    harness_version: str = HARNESS_VERSION

    @property
    def raw_output(self) -> Any:
        return self.provider_response.raw_output if self.provider_response else None

    @property
    def remote_side_effects(self) -> tuple[object, ...]:
        """The harness has no remote side-effect channel by construction."""

        return ()


class _GraphState(TypedDict, total=False):
    request: ModelAnalysisRequest
    status: str
    error: str | None
    provider_response: ModelCompletion | None
    tool_results: list[ToolResult]
    tool_call_count: int
    forbidden_attempts: list[str]
    checkpoints: list[AnalysisCheckpoint]


class LangGraphAnalysisHarness:
    """Run at most one final model call plus the declared tool budget."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        tool_registry: ToolRegistry | None = None,
        tool_context: ToolContext | None = None,
    ) -> None:
        if not isinstance(provider, ModelProvider):
            raise TypeError("analysis harness requires a provider-neutral model adapter")
        if tool_registry is not None and tool_context is not None:
            raise ValueError("provide tool_registry or tool_context, not both")
        self.provider = provider
        self._tool_registry = tool_registry
        self._tool_context = tool_context

    def build_graph(self, request: ModelAnalysisRequest) -> Any:
        """Compile the finite graph after validating the request boundary."""

        self._validate_request(request)
        graph = StateGraph(_GraphState)
        graph.add_node("prepare", self._prepare)
        graph.add_node("invoke_model", self._invoke_model)
        graph.add_node("dispatch_tools", self._dispatch_tools)
        graph.add_node("finish", self._finish)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "invoke_model")
        graph.add_conditional_edges(
            "invoke_model",
            self._after_model,
            {"dispatch_tools": "dispatch_tools", "finish": "finish"},
        )
        graph.add_conditional_edges(
            "dispatch_tools",
            self._after_tools,
            {"invoke_model": "invoke_model", "finish": "finish"},
        )
        graph.add_edge("finish", END)
        return graph.compile()

    def run(self, request: ModelAnalysisRequest) -> BoundedAnalysisResult:
        """Execute the bounded graph and return an explicit terminal status."""

        self._validate_request(request)
        initial: _GraphState = {
            "request": request,
            "status": "running",
            "error": None,
            "provider_response": None,
            "tool_results": [],
            "tool_call_count": 0,
            "forbidden_attempts": [],
            "checkpoints": [],
        }
        final = self.build_graph(request).invoke(initial)
        status = final.get("status", "failed")
        if status not in {"completed", "rejected", "failed"}:
            status = "failed"
        return BoundedAnalysisResult(
            request=request,
            status=status,  # type: ignore[arg-type]
            provider_response=final.get("provider_response"),
            checkpoints=tuple(final.get("checkpoints", [])),
            tool_results=tuple(final.get("tool_results", [])),
            forbidden_attempts=tuple(final.get("forbidden_attempts", [])),
            error=final.get("error"),
        )

    analyze = run
    run_analysis = run

    def _prepare(self, state: _GraphState) -> dict[str, Any]:
        request = state["request"]
        return {"checkpoints": [_checkpoint(request, stage="request_validated", status="running")]}

    def _invoke_model(self, state: _GraphState) -> dict[str, Any]:
        request = state["request"]
        try:
            response = self.provider.complete(
                request,
                tool_results=tuple(state.get("tool_results", [])),
            )
            _validate_completion(response, request)
        except ModelProviderTimeout as exc:
            return {
                "status": "failed",
                "error": "model provider timeout",
                "checkpoints": state.get("checkpoints", [])
                + [_checkpoint(request, stage="provider_timeout", status="failed", error=str(exc))],
            }
        except ModelProviderError as exc:
            return {
                "status": "failed",
                "error": "model provider failure",
                "checkpoints": state.get("checkpoints", [])
                + [_checkpoint(request, stage="provider_failure", status="failed", error=str(exc))],
            }
        except (AnalysisOutputError, ValueError, TypeError) as exc:
            return {
                "status": "failed",
                "error": str(exc),
                "checkpoints": state.get("checkpoints", [])
                + [_checkpoint(request, stage="output_rejected", status="failed", error=str(exc))],
            }
        return {
            "provider_response": response,
            "checkpoints": state.get("checkpoints", [])
            + [
                _checkpoint(
                    request,
                    stage="provider_response",
                    status="running",
                    response=response,
                    tool_call_count=state.get("tool_call_count", 0) + len(response.tool_calls),
                )
            ],
        }

    def _dispatch_tools(self, state: _GraphState) -> dict[str, Any]:
        request = state["request"]
        response = state.get("provider_response")
        if response is None:
            return {"status": "failed", "error": "tool dispatch has no provider response"}
        current_count = state.get("tool_call_count", 0)
        requested_count = current_count + len(response.tool_calls)
        if requested_count > request.budget.max_tool_calls:
            error = "model tool budget exceeded"
            return {
                "status": "rejected",
                "error": error,
                "forbidden_attempts": state.get("forbidden_attempts", [])
                + ["tool_budget_exceeded"],
                "checkpoints": state.get("checkpoints", [])
                + [
                    _checkpoint(
                        request,
                        stage="tool_budget_rejected",
                        status="rejected",
                        error=error,
                        response=response,
                        tool_call_count=requested_count,
                    )
                ],
            }
        registry = self._registry_for(request)
        results = list(state.get("tool_results", []))
        for call in response.tool_calls:
            try:
                results.append(registry.invoke(call))
            except ToolBoundaryError as exc:
                error = str(exc)
                return {
                    "status": "rejected",
                    "error": error,
                    "forbidden_attempts": state.get("forbidden_attempts", []) + [call.name],
                    "checkpoints": state.get("checkpoints", [])
                    + [
                        _checkpoint(
                            request,
                            stage="tool_rejected",
                            status="rejected",
                            error=error,
                            response=response,
                            tool_call_count=requested_count,
                        )
                    ],
                }
        return {
            "tool_results": results,
            "tool_call_count": requested_count,
            "checkpoints": state.get("checkpoints", [])
            + [
                _checkpoint(
                    request,
                    stage="tools_completed",
                    status="running",
                    response=response,
                    tool_call_count=requested_count,
                )
            ],
        }

    def _finish(self, state: _GraphState) -> dict[str, Any]:
        request = state["request"]
        status = state.get("status", "running")
        if status == "running":
            status = "completed"
        response = state.get("provider_response")
        return {
            "status": status,
            "checkpoints": state.get("checkpoints", [])
            + [
                _checkpoint(
                    request,
                    stage="finished",
                    status=status,
                    response=response,
                    error=state.get("error"),
                    tool_call_count=state.get("tool_call_count", 0),
                )
            ],
        }

    def _after_model(self, state: _GraphState) -> str:
        if state.get("status") != "running":
            return "finish"
        response = state.get("provider_response")
        return "dispatch_tools" if response is not None and response.tool_calls else "finish"

    def _after_tools(self, state: _GraphState) -> str:
        return "invoke_model" if state.get("status") == "running" else "finish"

    def _registry_for(self, request: ModelAnalysisRequest) -> ToolRegistry:
        if self._tool_registry is not None:
            if not set(request.allowed_tools).issubset(self._tool_registry.names()):
                raise AnalysisRequestError("request asks for tools absent from the fixed registry")
            return self._tool_registry
        return build_tool_registry(request, context=self._tool_context)

    def _validate_request(self, request: ModelAnalysisRequest) -> None:
        if not isinstance(request, ModelAnalysisRequest):
            raise AnalysisRequestError("analysis requires the typed ModelAnalysisRequest")
        if request.schema_version != CONTRACT_VERSION:
            raise AnalysisRequestError("unsupported analysis request schema version")
        if request.provider_mode is not request.replay_label:
            raise AnalysisRequestError("provider mode and replay/live label must match")
        if len(set(request.allowed_tools)) != len(request.allowed_tools):
            raise AnalysisRequestError("analysis request tools must be unique")
        registry = self._registry_for(request)
        if not set(request.allowed_tools).issubset(registry.names()):
            raise AnalysisRequestError("analysis request asks for an unavailable tool")
        metadata = self.provider.metadata
        if metadata.mode is not request.provider_mode:
            raise AnalysisRequestError("provider mode does not match analysis request")
        if metadata.request_schema_version != request.schema_version:
            raise AnalysisRequestError("provider does not support the request schema")
        if metadata.response_schema_version != CONTRACT_VERSION:
            raise AnalysisRequestError("provider response schema is unsupported")


BoundedAgentHarness = LangGraphAnalysisHarness
AnalysisGraph = LangGraphAnalysisHarness


def _validate_completion(response: ModelCompletion, request: ModelAnalysisRequest) -> None:
    if not isinstance(response, ModelCompletion):
        raise AnalysisOutputError("provider did not return a typed response envelope")
    metadata = response.metadata
    if metadata.mode is not request.provider_mode:
        raise AnalysisOutputError("provider response mode does not match request")
    if metadata.request_schema_version != request.schema_version:
        raise AnalysisOutputError("provider response request version is stale")
    if metadata.response_schema_version != CONTRACT_VERSION:
        raise AnalysisOutputError("provider response schema version is unsupported")
    if response.raw_output is None and not response.tool_calls:
        raise AnalysisOutputError("provider response is empty")
    if response.raw_output is not None:
        payload = response.raw_output
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")  # type: ignore[attr-defined]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise AnalysisOutputError("provider output is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise AnalysisOutputError("provider output must be a JSON object")
        _validate_advisory_payload(payload, request)


def _validate_advisory_payload(payload: Mapping[str, Any], request: ModelAnalysisRequest) -> None:
    """Validate the envelope without constructing T074 response/proposal objects."""

    if payload.get("schema_version") != CONTRACT_VERSION:
        raise AnalysisOutputError("provider output schema version is unsupported")
    allowed_fields = {
        "schema_version",
        "analysis_id",
        "provider",
        "model",
        "tenant_id",
        "case_id",
        "correlation_id",
        "attributions",
        "proposals",
        "uncertainty",
        "refusal_records",
        "token_count",
        "estimated_cost",
        "input_references",
    }
    unknown = set(payload) - allowed_fields
    if unknown:
        raise AnalysisOutputError(f"provider output contains unsupported fields: {sorted(unknown)}")
    for name in ("analysis_id", "uncertainty"):
        if not isinstance(payload.get(name), str) or not payload[name].strip():
            raise AnalysisOutputError(f"provider output {name} is required")
    for name in ("tenant_id", "case_id", "correlation_id"):
        value = payload.get(name)
        if value is not None and value != getattr(request, name):
            raise AnalysisOutputError(f"provider output {name} crosses request scope")
    for name in ("provider", "model"):
        value = payload.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise AnalysisOutputError(f"provider output {name} is invalid")

    allowed_evidence = set(request.evidence_references)
    representation = request.redacted_case_representation
    allowed_timeline = {
        value.get("timeline_event_id")
        for value in representation.get("timeline", [])
        if isinstance(value, Mapping) and isinstance(value.get("timeline_event_id"), str)
    }
    input_references = payload.get("input_references", ())
    _validate_references(input_references, allowed_evidence | allowed_timeline, "input")
    _validate_attributions(payload.get("attributions", ()), allowed_timeline, allowed_evidence)
    _validate_proposals(payload.get("proposals", ()), allowed_timeline, allowed_evidence, request)
    refusal_records = payload.get("refusal_records", ())
    if not _sequence_of_strings(refusal_records):
        raise AnalysisOutputError("provider refusal records are invalid")
    token_count = payload.get("token_count")
    if token_count is not None and (
        isinstance(token_count, bool) or not isinstance(token_count, int) or token_count < 0
    ):
        raise AnalysisOutputError("provider token count is invalid")
    estimated_cost = payload.get("estimated_cost")
    if estimated_cost is not None:
        try:
            if estimated_cost < 0:
                raise AnalysisOutputError("provider cost is invalid")
        except TypeError as exc:
            raise AnalysisOutputError("provider cost is invalid") from exc


def _validate_attributions(
    values: Any,
    allowed_timeline: set[str],
    allowed_evidence: set[str],
) -> None:
    if not _sequence(values):
        raise AnalysisOutputError("provider attributions must be a sequence")
    allowed_fields = {
        "timeline_event_id",
        "label",
        "confidence",
        "rationale",
        "evidence_references",
        "method",
        "model_or_rules_version",
    }
    for value in values:
        if not isinstance(value, Mapping) or set(value) - allowed_fields:
            raise AnalysisOutputError("provider attribution is malformed")
        event_id = value.get("timeline_event_id")
        if not isinstance(event_id, str) or event_id not in allowed_timeline:
            raise AnalysisOutputError("provider attribution references an unknown timeline event")
        label = value.get("label")
        if label not in {item.value for item in AttributionLabel}:
            raise AnalysisOutputError("provider attribution label is unsupported")
        confidence = value.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, int | float)
            or not 0 <= confidence <= 1
        ):
            raise AnalysisOutputError("provider attribution confidence is out of bounds")
        if not isinstance(value.get("rationale"), str) or not value["rationale"].strip():
            raise AnalysisOutputError("provider attribution rationale is required")
        _validate_references(value.get("evidence_references", ()), allowed_evidence, "attribution")


def _validate_proposals(
    values: Any,
    allowed_timeline: set[str],
    allowed_evidence: set[str],
    request: ModelAnalysisRequest,
) -> None:
    if not _sequence(values):
        raise AnalysisOutputError("provider proposals must be a sequence")
    allowed_fields = {
        "proposal_id",
        "tenant_id",
        "case_id",
        "action_type",
        "target_resource",
        "parameters",
        "rationale",
        "evidence_references",
        "attribution_references",
        "requested_amount_minor",
        "currency",
        "idempotency_key",
        "analysis_id",
    }
    for value in values:
        if not isinstance(value, Mapping) or set(value) - allowed_fields:
            raise AnalysisOutputError("provider proposal contains unsupported fields")
        for name in ("tenant_id", "case_id"):
            if name in value and value[name] != getattr(request, name):
                raise AnalysisOutputError("provider proposal crosses request scope")
        if value.get("action_type") not in {item.value for item in ActionType}:
            raise AnalysisOutputError("provider proposal action is unsupported")
        for name in ("proposal_id", "target_resource", "rationale", "idempotency_key"):
            if name in value and (not isinstance(value[name], str) or not value[name].strip()):
                raise AnalysisOutputError(f"provider proposal {name} is invalid")
        _validate_references(value.get("evidence_references", ()), allowed_evidence, "proposal")
        _validate_references(
            value.get("attribution_references", ()), allowed_timeline, "proposal attribution"
        )
        if "requested_amount_minor" in value or "currency" in value:
            raise AnalysisOutputError(
                "model monetary output requires later deterministic financial validation"
            )


def _validate_references(value: Any, allowed: set[str], name: str) -> None:
    if not _sequence(value) or any(not isinstance(item, str) for item in value):
        raise AnalysisOutputError(f"provider {name} references are invalid")
    if not set(value).issubset(allowed):
        raise AnalysisOutputError(f"provider {name} references include an unknown identity")


def _sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


def _sequence_of_strings(value: Any) -> bool:
    return _sequence(value) and all(isinstance(item, str) and item.strip() for item in value)


def _checkpoint(
    request: ModelAnalysisRequest,
    *,
    stage: str,
    status: str,
    response: ModelCompletion | None = None,
    tool_call_count: int = 0,
    error: str | None = None,
) -> AnalysisCheckpoint:
    metadata: ProviderMetadata | None = response.metadata if response is not None else None
    return AnalysisCheckpoint(
        stage=stage,
        request_checksum=_request_checksum(request),
        mode=request.provider_mode.value,
        provider=metadata.provider if metadata is not None else None,
        model=metadata.model if metadata is not None else None,
        tool_call_count=tool_call_count,
        status=status,
        error=error,
    )


def _request_checksum(request: ModelAnalysisRequest) -> str:
    encoded = json.dumps(
        redact_value(request.model_dump(mode="json")),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "AnalysisCheckpoint",
    "AnalysisGraph",
    "AnalysisHarnessError",
    "AnalysisOutputError",
    "AnalysisRequestError",
    "BoundedAgentHarness",
    "BoundedAnalysisResult",
    "HARNESS_VERSION",
    "LangGraphAnalysisHarness",
]
