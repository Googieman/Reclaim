"""Strict parsing for untrusted bounded-model analysis responses.

The provider response is not an authority boundary.  This module converts only
the approved response contract into typed values and keeps provider/replay
metadata beside, rather than inside, the business response.  In particular,
model-supplied money is rejected here: deterministic exposure remains the only
source of financial truth and a later task owns proposal validation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from packages.contracts.analysis_policy import (
    AttributionLabel,
    AttributionSuggestion,
    ModelAnalysisRequest,
    ModelAnalysisResponse,
    TypedActionProposal,
)
from packages.contracts.common import CONTRACT_VERSION
from pydantic import Field, ValidationError

from .providers import ModelCompletion, ProviderMetadata

OUTPUT_PARSER_VERSION = "analysis-output-parser-v1.0.0"


class AnalysisResponseError(ValueError):
    """The untrusted model output cannot be accepted as the typed response."""


class UnsupportedAnalysisResponse(AnalysisResponseError):
    """The response schema or provider metadata is unsupported or stale."""


class AnalysisResponseScopeError(AnalysisResponseError):
    """The response attempts to cross the request tenant/case boundary."""


class AnalysisReferenceError(AnalysisResponseError):
    """The response contains an unknown evidence, timeline, or input reference."""


class AnalysisFinancialOutputError(AnalysisResponseError):
    """The model attempted to make a financial value authoritative."""


class TenantBoundAnalysisResponse(ModelAnalysisResponse):
    """The T074 response view with the required case binding.

    The pre-existing shared response contract accidentally omits ``case_id``
    even though the model-analysis contract and T065 require it.  This local
    subtype preserves compatibility with the shared type while keeping the
    missing binding mandatory here; the shared contract file is intentionally
    left unchanged.
    """

    case_id: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class AnalysisResponseProvenance:
    """Validated metadata retained outside the provider-controlled response body."""

    analysis_id: str
    tenant_id: str
    case_id: str
    correlation_id: str
    provider: str
    model: str
    mode: str
    request_schema_version: str
    response_schema_version: str
    parser_version: str
    input_references: tuple[str, ...]
    output_references: tuple[str, ...]
    uncertainty_references: tuple[str, ...]
    token_count: int | None
    estimated_cost: Decimal | None
    response_checksum: str


@dataclass(frozen=True, slots=True)
class ParsedAnalysisResponse:
    """A typed advisory response plus trusted boundary metadata."""

    response: ModelAnalysisResponse
    provenance: AnalysisResponseProvenance

    @property
    def analysis_id(self) -> str:
        return self.response.analysis_id

    @property
    def proposals(self) -> tuple[TypedActionProposal, ...]:
        return self.response.proposals

    @property
    def attributions(self) -> tuple[AttributionSuggestion, ...]:
        return self.response.attributions


class AnalysisResponseParser:
    """Parse one provider-neutral response using a typed request binding."""

    def parse(
        self,
        raw_output: Any,
        request: ModelAnalysisRequest,
        *,
        provider_metadata: ProviderMetadata | None = None,
        completion: ModelCompletion | None = None,
        deterministic_uncertainty: Sequence[str] = (),
    ) -> ModelAnalysisResponse:
        return self.parse_with_provenance(
            raw_output,
            request,
            provider_metadata=provider_metadata,
            completion=completion,
            deterministic_uncertainty=deterministic_uncertainty,
        ).response

    def parse_with_provenance(
        self,
        raw_output: Any,
        request: ModelAnalysisRequest,
        *,
        provider_metadata: ProviderMetadata | None = None,
        completion: ModelCompletion | None = None,
        deterministic_uncertainty: Sequence[str] = (),
    ) -> ParsedAnalysisResponse:
        if isinstance(raw_output, ModelCompletion):
            if completion is not None:
                raise AnalysisResponseError("completion metadata was supplied twice")
            completion = raw_output
            raw_output = completion.raw_output
        if completion is not None:
            if raw_output is not None and raw_output != completion.raw_output:
                raise AnalysisResponseError("completion and raw response do not match")
            raw_output = completion.raw_output
            if provider_metadata is not None and provider_metadata != completion.metadata:
                raise AnalysisResponseError("provider metadata does not match completion")
            provider_metadata = completion.metadata

        _validate_request(request)
        metadata = _validate_provider_metadata(provider_metadata, request)
        payload = _decode_payload(raw_output)
        input_references = _validate_response_envelope(
            payload,
            request,
            metadata=metadata,
            deterministic_uncertainty=deterministic_uncertainty,
        )

        normalized = dict(payload)
        normalized["token_count"] = _provider_metadata_value(
            payload,
            "token_count",
            completion.token_count if completion is not None else None,
        )
        normalized["estimated_cost"] = _provider_metadata_value(
            payload,
            "estimated_cost",
            completion.estimated_cost if completion is not None else None,
        )

        try:
            response = TenantBoundAnalysisResponse.model_validate(normalized)
        except (ValidationError, TypeError, ValueError) as exc:
            raise AnalysisResponseError(
                f"analysis response violates the typed schema: {exc}"
            ) from exc

        uncertainty_references = _uncertainty_references(
            request, deterministic_uncertainty=deterministic_uncertainty
        )
        output_references = tuple(
            sorted(
                {
                    *(f"attribution:{item.timeline_event_id}" for item in response.attributions),
                    *(f"proposal:{item.proposal_id}" for item in response.proposals),
                }
            )
        )
        response_checksum = _checksum(response.model_dump(mode="json"))
        provenance = AnalysisResponseProvenance(
            analysis_id=response.analysis_id,
            tenant_id=response.tenant_id,
            case_id=response.case_id,
            correlation_id=response.correlation_id,
            provider=response.provider,
            model=response.model,
            mode=request.provider_mode.value,
            request_schema_version=request.schema_version,
            response_schema_version=response.schema_version,
            parser_version=OUTPUT_PARSER_VERSION,
            input_references=input_references,
            output_references=output_references,
            uncertainty_references=uncertainty_references,
            token_count=response.token_count,
            estimated_cost=response.estimated_cost,
            response_checksum=response_checksum,
        )
        return ParsedAnalysisResponse(response=response, provenance=provenance)


def parse_analysis_response(
    raw_output: Any,
    request: ModelAnalysisRequest,
    *,
    provider_metadata: ProviderMetadata | None = None,
    completion: ModelCompletion | None = None,
    deterministic_uncertainty: Sequence[str] = (),
) -> ModelAnalysisResponse:
    """Parse untrusted provider output into the exact approved response model."""

    return AnalysisResponseParser().parse(
        raw_output,
        request,
        provider_metadata=provider_metadata,
        completion=completion,
        deterministic_uncertainty=deterministic_uncertainty,
    )


def parse_validated_analysis_response(
    raw_output: Any,
    request: ModelAnalysisRequest,
    *,
    provider_metadata: ProviderMetadata | None = None,
    completion: ModelCompletion | None = None,
    deterministic_uncertainty: Sequence[str] = (),
) -> ParsedAnalysisResponse:
    """Return the typed response and its separately retained provenance."""

    return AnalysisResponseParser().parse_with_provenance(
        raw_output,
        request,
        provider_metadata=provider_metadata,
        completion=completion,
        deterministic_uncertainty=deterministic_uncertainty,
    )


def _validate_request(request: ModelAnalysisRequest) -> None:
    if not isinstance(request, ModelAnalysisRequest):
        raise AnalysisResponseError("analysis response requires a typed analysis request")
    if request.schema_version != CONTRACT_VERSION:
        raise UnsupportedAnalysisResponse("analysis request schema version is unsupported")
    if request.provider_mode is not request.replay_label:
        raise UnsupportedAnalysisResponse("analysis request mode and replay label do not match")


def _validate_provider_metadata(
    metadata: ProviderMetadata | None, request: ModelAnalysisRequest
) -> ProviderMetadata | None:
    if metadata is None:
        return None
    if not isinstance(metadata, ProviderMetadata):
        raise AnalysisResponseError("provider metadata must use the typed provider envelope")
    if metadata.request_schema_version != request.schema_version:
        raise UnsupportedAnalysisResponse("provider request schema version is stale")
    if metadata.response_schema_version != CONTRACT_VERSION:
        raise UnsupportedAnalysisResponse("provider response schema version is unsupported")
    if metadata.mode is not request.provider_mode:
        raise UnsupportedAnalysisResponse("provider mode does not match the analysis request")
    return metadata


def _decode_payload(raw_output: Any) -> dict[str, Any]:
    if raw_output is None:
        raise AnalysisResponseError("analysis response is empty")
    payload = raw_output
    if isinstance(payload, ModelAnalysisResponse):
        payload = payload.model_dump(mode="json")
    elif hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise AnalysisResponseError("analysis response is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise AnalysisResponseError("analysis response must be a JSON object")
    return dict(payload)


def _validate_response_envelope(
    payload: Mapping[str, Any],
    request: ModelAnalysisRequest,
    *,
    metadata: ProviderMetadata | None,
    deterministic_uncertainty: Sequence[str],
) -> tuple[str, ...]:
    allowed_fields = set(TenantBoundAnalysisResponse.model_fields)
    unknown = set(payload) - allowed_fields
    if unknown:
        raise UnsupportedAnalysisResponse(
            f"analysis response contains unsupported fields: {sorted(unknown)}"
        )
    if payload.get("schema_version") != CONTRACT_VERSION:
        raise UnsupportedAnalysisResponse("analysis response schema version is unsupported")

    for name in ("tenant_id", "case_id", "correlation_id"):
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise AnalysisResponseScopeError(f"analysis response {name} is required")
        if value != getattr(request, name):
            raise AnalysisResponseScopeError(f"analysis response {name} crosses request scope")
    for name in ("analysis_id", "provider", "model", "uncertainty"):
        _required_text(payload.get(name), f"analysis response {name}")
    if metadata is not None:
        if payload["provider"] != metadata.provider or payload["model"] != metadata.model:
            raise AnalysisResponseError("response provider/model metadata does not match envelope")

    allowed_evidence = _allowed_evidence(request)
    allowed_timeline = _allowed_timeline(request)
    _validate_attributions(payload.get("attributions", ()), allowed_timeline, allowed_evidence)
    _validate_proposals(
        payload.get("proposals", ()),
        request=request,
        analysis_id=payload["analysis_id"],
        allowed_timeline=allowed_timeline,
        allowed_evidence=allowed_evidence,
    )
    _validate_refusals(payload.get("refusal_records", ()))
    _validate_token_and_cost(payload.get("token_count"), payload.get("estimated_cost"))

    deterministic_references = _uncertainty_references(
        request, deterministic_uncertainty=deterministic_uncertainty
    )
    uncertainty = payload["uncertainty"]
    if deterministic_references and any(
        reference not in uncertainty for reference in deterministic_references
    ):
        raise AnalysisResponseError("analysis response attempts to erase deterministic uncertainty")
    # Input provenance is derived from the request boundary, never accepted as
    # an undeclared model-controlled response field.
    return tuple(sorted(allowed_evidence | allowed_timeline))


def _validate_attributions(
    values: Any, allowed_timeline: set[str], allowed_evidence: set[str]
) -> None:
    values = _sequence(values, "attributions")
    allowed_fields = set(AttributionSuggestion.model_fields)
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise AnalysisResponseError(f"attribution {index} must be an object")
        unknown = set(value) - allowed_fields
        if unknown:
            raise UnsupportedAnalysisResponse(
                f"attribution {index} contains unsupported fields: {sorted(unknown)}"
            )
        event_id = _required_text(value.get("timeline_event_id"), "attribution timeline_event_id")
        if event_id not in allowed_timeline:
            raise AnalysisReferenceError("attribution references an unknown timeline event")
        if value.get("label") not in {item.value for item in AttributionLabel}:
            raise AnalysisResponseError("attribution label is unsupported")
        confidence = value.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, int | float)
            or not math.isfinite(float(confidence))
            or not 0 <= confidence <= 1
        ):
            raise AnalysisResponseError("attribution confidence is out of bounds")
        _required_text(value.get("rationale"), "attribution rationale")
        _required_text(value.get("method"), "attribution method")
        _required_text(value.get("model_or_rules_version"), "attribution version")
        references = _references(value.get("evidence_references", ()), "attribution evidence")
        if not set(references).issubset(allowed_evidence):
            raise AnalysisReferenceError("attribution references unknown evidence")


def _validate_proposals(
    values: Any,
    *,
    request: ModelAnalysisRequest,
    analysis_id: str,
    allowed_timeline: set[str],
    allowed_evidence: set[str],
) -> None:
    # Import lazily to keep the parser/proposal modules independently importable.
    from .proposals import construct_typed_proposals

    values = _sequence(values, "proposals")
    try:
        construct_typed_proposals(
            values,
            request=request,
            analysis_id=analysis_id,
            allowed_timeline=allowed_timeline,
            allowed_evidence=allowed_evidence,
        )
    except AnalysisResponseError:
        raise
    except (TypeError, ValueError, ValidationError) as exc:
        raise AnalysisResponseError(f"typed proposal construction failed: {exc}") from exc


def _validate_refusals(values: Any) -> None:
    values = _sequence(values, "refusal records")
    for value in values:
        _required_text(value, "refusal record")


def _validate_token_and_cost(token_count: Any, estimated_cost: Any) -> None:
    if token_count is not None and (
        isinstance(token_count, bool) or not isinstance(token_count, int) or token_count < 0
    ):
        raise AnalysisResponseError("token count is invalid")
    if estimated_cost is not None:
        _decimal(estimated_cost, "estimated cost")


def _provider_metadata_value(payload: Mapping[str, Any], name: str, provider_value: Any) -> Any:
    raw_value = payload.get(name)
    if provider_value is not None:
        if raw_value is not None:
            if name == "estimated_cost":
                if _decimal(raw_value, name) != _decimal(provider_value, name):
                    raise AnalysisResponseError(f"response {name} does not match provider metadata")
            elif raw_value != provider_value:
                raise AnalysisResponseError(f"response {name} does not match provider metadata")
        return provider_value
    if name == "estimated_cost" and raw_value is not None:
        return _decimal(raw_value, name)
    return raw_value


def _allowed_evidence(request: ModelAnalysisRequest) -> set[str]:
    representation = request.redacted_case_representation
    values = representation.get("evidence", ()) if isinstance(representation, Mapping) else ()
    identifiers = {
        item.get("evidence_id")
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("evidence_id"), str)
    }
    identifiers.update(request.evidence_references)
    timeline = representation.get("timeline", ()) if isinstance(representation, Mapping) else ()
    for item in timeline:
        if isinstance(item, Mapping):
            references = item.get("evidence_references", ())
            if isinstance(references, Sequence) and not isinstance(references, str | bytes):
                identifiers.update(
                    reference for reference in references if isinstance(reference, str)
                )
    return {value for value in identifiers if isinstance(value, str) and value.strip()}


def _allowed_timeline(request: ModelAnalysisRequest) -> set[str]:
    representation = request.redacted_case_representation
    values = representation.get("timeline", ()) if isinstance(representation, Mapping) else ()
    return {
        item["timeline_event_id"]
        for item in values
        if isinstance(item, Mapping)
        and isinstance(item.get("timeline_event_id"), str)
        and item["timeline_event_id"].strip()
    }


def _uncertainty_references(
    request: ModelAnalysisRequest, *, deterministic_uncertainty: Sequence[str]
) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(request.redacted_case_representation, Mapping):
        context_values = request.redacted_case_representation.get("uncertainty", ())
        if isinstance(context_values, Sequence) and not isinstance(context_values, str | bytes):
            values.extend(context_values)
    values.extend(deterministic_uncertainty)
    return _references(values, "uncertainty")


def _sequence(value: Any, name: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise AnalysisResponseError(f"{name} must be a sequence")
    return tuple(value)


def _references(value: Any, name: str) -> tuple[str, ...]:
    values = _sequence(value, f"{name} references")
    result: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise AnalysisReferenceError(f"{name} references contain an invalid identity")
        result.append(item.strip())
    return tuple(sorted(set(result)))


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisResponseError(f"{name} is required")
    return value.strip()


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal | int | float | str):
        raise AnalysisResponseError(f"{name} is invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AnalysisResponseError(f"{name} is invalid") from exc
    if not result.is_finite() or result < 0:
        raise AnalysisResponseError(f"{name} is invalid")
    return result


def _checksum(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


OutputParser = AnalysisResponseParser
TypedAnalysisResponseParser = AnalysisResponseParser


__all__ = [
    "AnalysisFinancialOutputError",
    "AnalysisReferenceError",
    "AnalysisResponseError",
    "AnalysisResponseParser",
    "AnalysisResponseProvenance",
    "AnalysisResponseScopeError",
    "OUTPUT_PARSER_VERSION",
    "OutputParser",
    "ParsedAnalysisResponse",
    "TenantBoundAnalysisResponse",
    "TypedAnalysisResponseParser",
    "UnsupportedAnalysisResponse",
    "parse_analysis_response",
    "parse_validated_analysis_response",
]
