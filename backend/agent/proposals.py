"""Typed, non-executable proposal construction at the model boundary.

This is intentionally not the deterministic proposal validator.  T074 only
converts a strictly bounded model response into the shared typed contract and
records a fail-closed rejection.  Policy, connector allowlists, and execution
remain downstream concerns owned by later tasks.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from packages.contracts.analysis_policy import (
    ActionType,
    ModelAnalysisRequest,
    ModelAnalysisResponse,
)
from packages.contracts.common import CONTRACT_VERSION

from .output_parser import (
    AnalysisFinancialOutputError,
    AnalysisReferenceError,
    AnalysisResponseError,
    ParsedAnalysisResponse,
    parse_validated_analysis_response,
)
from .providers import ModelCompletion, ProviderMetadata

PROPOSAL_BOUNDARY_VERSION = "typed-proposal-boundary-v1.0.0"

_FORBIDDEN_KEY_PARTS = frozenset(
    {
        "account",
        "api_key",
        "attacker",
        "authorization",
        "bearer",
        "client_secret",
        "command",
        "cookie",
        "credential",
        "database",
        "filesystem",
        "http_request",
        "network",
        "password",
        "private_key",
        "query",
        "raw_sql",
        "secret",
        "shell",
        "sql",
        "token",
        "url",
    }
)
_FORBIDDEN_OPERATION_PARTS = frozenset(
    {
        "account",
        "attacker",
        "cancel",
        "credential",
        "database",
        "execute",
        "financial",
        "fund",
        "network",
        "payment",
        "probe",
        "refund",
        "restore",
        "shell",
        "sql",
        "transfer",
    }
)
_FORBIDDEN_STRING_PATTERNS = (
    re.compile(r"\b(?:bash|cmd|powershell|pwsh|sh)\b", re.IGNORECASE),
    re.compile(r"\b(?:curl|wget|invoke-webrequest)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:select|insert|update|delete|drop|alter)\b.{0,40}\b(?:from|into|table|where)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:https?|file)://", re.IGNORECASE),
)


class ProposalBoundaryError(AnalysisResponseError):
    """A typed proposal could not be safely constructed."""


class ForbiddenProposalError(ProposalBoundaryError):
    """The untrusted output contains a forbidden capability or operation."""


@dataclass(frozen=True, slots=True)
class ProposalBoundaryAudit:
    """Small, append-only-ready rejection evidence; no raw executable payload."""

    outcome: Literal["accepted", "rejected", "forbidden_operation"]
    boundary_version: str
    tenant_id: str | None = None
    case_id: str | None = None
    correlation_id: str | None = None
    analysis_id: str | None = None
    operation: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "boundary_version": self.boundary_version,
            "tenant_id": self.tenant_id,
            "case_id": self.case_id,
            "correlation_id": self.correlation_id,
            "analysis_id": self.analysis_id,
            "operation": self.operation,
            "reason": self.reason,
            "side_effects": False,
        }


@dataclass(frozen=True, slots=True)
class ProposalBoundaryResult:
    """Side-effect-free proposal result returned by ``TypedProposalBoundary``."""

    status: Literal["accepted", "rejected"]
    proposals: tuple[Any, ...]
    audit_record: Mapping[str, Any]
    forbidden_attempts: tuple[str, ...] = ()
    analysis_response: ModelAnalysisResponse | None = None
    parsed_response: ParsedAnalysisResponse | None = None
    error: str | None = None
    boundary_version: str = PROPOSAL_BOUNDARY_VERSION

    @property
    def remote_side_effects(self) -> tuple[object, ...]:
        return ()

    def __getitem__(self, name: str) -> Any:
        return getattr(self, name)

    def get(self, name: str, default: Any = None) -> Any:
        return getattr(self, name, default)


def construct_typed_proposals(
    values: Any,
    *,
    request: ModelAnalysisRequest,
    analysis_id: str,
    allowed_timeline: set[str] | None = None,
    allowed_evidence: set[str] | None = None,
) -> tuple[Any, ...]:
    """Construct shared ``TypedActionProposal`` values from untrusted mappings.

    Model-supplied monetary fields are deliberately prohibited.  A future
    deterministic stage may create or validate a refund proposal using the
    authoritative exposure/payment facts; this boundary never accepts a model
    value as that authority.
    """

    if not isinstance(request, ModelAnalysisRequest):
        raise ProposalBoundaryError("typed proposals require a typed analysis request")
    if not isinstance(analysis_id, str) or not analysis_id.strip():
        raise ProposalBoundaryError("analysis_id is required")
    if not isinstance(values, Sequence) or isinstance(values, str | bytes):
        raise ProposalBoundaryError("proposals must be a sequence")

    timeline = allowed_timeline if allowed_timeline is not None else _allowed_timeline(request)
    evidence = allowed_evidence if allowed_evidence is not None else _allowed_evidence(request)
    result: list[Any] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise ProposalBoundaryError(f"proposal {index} must be an object")
        forbidden = find_forbidden_operation(value)
        if forbidden is not None:
            raise ForbiddenProposalError(f"forbidden proposal operation: {forbidden}")

        proposal_fields = set(_proposal_model_fields())
        unknown = set(value) - proposal_fields
        if unknown:
            raise ProposalBoundaryError(
                f"proposal {index} contains unsupported fields: {sorted(unknown)}"
            )
        if value.get("schema_version", CONTRACT_VERSION) != CONTRACT_VERSION:
            raise ProposalBoundaryError("typed proposal schema version is unsupported")

        for name, expected in (
            ("tenant_id", request.tenant_id),
            ("case_id", request.case_id),
            ("correlation_id", request.correlation_id),
        ):
            actual = value.get(name)
            if not isinstance(actual, str) or not actual.strip():
                raise ProposalBoundaryError(f"proposal {name} is required")
            if actual != expected:
                raise AnalysisReferenceError(f"proposal {name} crosses request scope")

        proposal_analysis_id = _required_text(value.get("analysis_id"), "proposal analysis_id")
        if proposal_analysis_id != analysis_id:
            raise ProposalBoundaryError("proposal analysis_id does not match response")
        action_type = _required_text(value.get("action_type"), "proposal action_type")
        if action_type not in {item.value for item in ActionType}:
            raise ProposalBoundaryError("proposal action type is unsupported")

        # Money is a deterministic concern.  Presence of either field is rejected,
        # even when null, so a model cannot smuggle an authority claim through a
        # partially populated object.
        if "requested_amount_minor" in value or "currency" in value:
            raise AnalysisFinancialOutputError(
                "model monetary output is prohibited at the advisory boundary"
            )
        if action_type == ActionType.REFUND_PAYMENT.value:
            raise AnalysisFinancialOutputError(
                "refund proposals require deterministic financial validation"
            )

        parameters = value.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ProposalBoundaryError("proposal parameters must be an object")
        _validate_safe_parameters(parameters)
        evidence_references = _references(value.get("evidence_references", ()), "proposal evidence")
        attribution_references = _references(
            value.get("attribution_references", ()), "proposal attribution"
        )
        if not set(evidence_references).issubset(evidence):
            raise AnalysisReferenceError("proposal references unknown evidence")
        if not set(attribution_references).issubset(timeline):
            raise AnalysisReferenceError("proposal references unknown timeline event")

        proposal = {
            "schema_version": CONTRACT_VERSION,
            "tenant_id": request.tenant_id,
            "correlation_id": request.correlation_id,
            "proposal_id": _required_text(value.get("proposal_id"), "proposal_id"),
            "case_id": request.case_id,
            "action_type": action_type,
            "target_resource": _required_text(value.get("target_resource"), "target_resource"),
            "parameters": dict(parameters),
            "rationale": _required_text(value.get("rationale"), "proposal rationale"),
            "evidence_references": evidence_references,
            "attribution_references": attribution_references,
            "idempotency_key": _required_text(value.get("idempotency_key"), "idempotency_key"),
            "analysis_id": analysis_id,
        }
        try:
            from packages.contracts.analysis_policy import TypedActionProposal

            result.append(TypedActionProposal.model_validate(proposal))
        except (TypeError, ValueError) as exc:
            raise ProposalBoundaryError(
                f"proposal {index} violates the typed contract: {exc}"
            ) from exc
    return tuple(result)


def build_typed_proposals(
    values: Any,
    *,
    request: ModelAnalysisRequest,
    analysis_id: str,
    allowed_timeline: set[str] | None = None,
    allowed_evidence: set[str] | None = None,
) -> tuple[Any, ...]:
    """Compatibility name for the T074 typed proposal construction operation."""

    return construct_typed_proposals(
        values,
        request=request,
        analysis_id=analysis_id,
        allowed_timeline=allowed_timeline,
        allowed_evidence=allowed_evidence,
    )


class TypedProposalBoundary:
    """Validate advisory output without submitting anything to an action gateway."""

    def __init__(
        self,
        request: ModelAnalysisRequest | None = None,
        *,
        provider_metadata: ProviderMetadata | None = None,
        deterministic_uncertainty: Sequence[str] = (),
    ) -> None:
        self.request = request
        self.provider_metadata = provider_metadata
        self.deterministic_uncertainty = tuple(deterministic_uncertainty)

    def process(
        self,
        raw_output: Any,
        *,
        request: ModelAnalysisRequest | None = None,
        provider_metadata: ProviderMetadata | None = None,
        remote_action_gateway: object | None = None,
        deterministic_uncertainty: Sequence[str] = (),
    ) -> ProposalBoundaryResult:
        del remote_action_gateway  # Explicitly no execution channel at T074.
        bound_request = request or self.request
        completion = raw_output if isinstance(raw_output, ModelCompletion) else None
        payload = completion.raw_output if completion is not None else _payload_for_scan(raw_output)
        forbidden = find_forbidden_operation(payload)
        context = _untrusted_context(payload)
        if forbidden is not None:
            audit = ProposalBoundaryAudit(
                outcome="forbidden_operation",
                boundary_version=PROPOSAL_BOUNDARY_VERSION,
                operation=forbidden,
                reason="untrusted model output contains a forbidden capability",
                **context,
            )
            return ProposalBoundaryResult(
                status="rejected",
                proposals=(),
                audit_record=audit.as_dict(),
                forbidden_attempts=(forbidden,),
                error=audit.reason,
            )

        try:
            if bound_request is None:
                raise ProposalBoundaryError(
                    "a non-forbidden response requires a tenant/case-bound analysis request"
                )
            parsed = parse_validated_analysis_response(
                raw_output,
                bound_request,
                provider_metadata=provider_metadata or self.provider_metadata,
                deterministic_uncertainty=(
                    tuple(deterministic_uncertainty) or self.deterministic_uncertainty
                ),
            )
        except AnalysisResponseError as exc:
            audit = ProposalBoundaryAudit(
                outcome="rejected",
                boundary_version=PROPOSAL_BOUNDARY_VERSION,
                reason=str(exc),
                **context,
            )
            return ProposalBoundaryResult(
                status="rejected",
                proposals=(),
                audit_record=audit.as_dict(),
                error=str(exc),
            )
        audit = ProposalBoundaryAudit(
            outcome="accepted",
            boundary_version=PROPOSAL_BOUNDARY_VERSION,
            tenant_id=parsed.response.tenant_id,
            case_id=parsed.response.case_id,
            correlation_id=parsed.response.correlation_id,
            analysis_id=parsed.response.analysis_id,
            reason="typed advisory proposals constructed; no execution authorized",
        )
        return ProposalBoundaryResult(
            status="accepted",
            proposals=parsed.proposals,
            audit_record=audit.as_dict(),
            analysis_response=parsed.response,
            parsed_response=parsed,
        )


def find_forbidden_operation(value: Any) -> str | None:
    """Find a high-signal forbidden operation without interpreting instructions."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_name = _normalized_name(key)
            if _forbidden_key(key_name):
                return key_name
            if key_name in {"operation", "capability", "command", "tool"}:
                if isinstance(item, str) and _forbidden_operation(item):
                    return item.strip()
            if key_name == "action_type" and isinstance(item, str):
                # These are approved typed proposal classes.  Their eventual
                # execution/approval semantics belong downstream; T074 only
                # ensures the model did not emit an unknown operation.
                if _normalized_name(item) not in {action.value for action in ActionType}:
                    if _forbidden_operation(item):
                        return item.strip()
            if key_name == "target_resource" and isinstance(item, str):
                if any(pattern.search(item) for pattern in _FORBIDDEN_STRING_PATTERNS):
                    return item.strip()
            found = find_forbidden_operation(item)
            if found is not None:
                return found
        return None
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for item in value:
            found = find_forbidden_operation(item)
            if found is not None:
                return found
        return None
    return None


def _payload_for_scan(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _untrusted_context(value: Any) -> dict[str, str | None]:
    payload = value if isinstance(value, Mapping) else {}
    return {
        name: payload.get(name) if isinstance(payload.get(name), str) else None
        for name in ("tenant_id", "case_id", "correlation_id", "analysis_id")
    }


def _proposal_model_fields() -> tuple[str, ...]:
    from packages.contracts.analysis_policy import TypedActionProposal

    return tuple(TypedActionProposal.model_fields)


def _allowed_evidence(request: ModelAnalysisRequest) -> set[str]:
    values = request.redacted_case_representation.get("evidence", ())
    identifiers = set(request.evidence_references)
    identifiers.update(
        item.get("evidence_id")
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("evidence_id"), str)
    )
    for item in request.redacted_case_representation.get("timeline", ()):
        if isinstance(item, Mapping):
            references = item.get("evidence_references", ())
            if isinstance(references, Sequence) and not isinstance(references, str | bytes):
                identifiers.update(
                    reference for reference in references if isinstance(reference, str)
                )
    return {value for value in identifiers if isinstance(value, str) and value.strip()}


def _allowed_timeline(request: ModelAnalysisRequest) -> set[str]:
    values = request.redacted_case_representation.get("timeline", ())
    return {
        item["timeline_event_id"]
        for item in values
        if isinstance(item, Mapping)
        and isinstance(item.get("timeline_event_id"), str)
        and item["timeline_event_id"].strip()
    }


def _validate_safe_parameters(value: Mapping[str, Any]) -> None:
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ProposalBoundaryError("proposal parameter keys must be non-blank strings")
        key_name = _normalized_name(key)
        if _forbidden_key(key_name) or key_name in {
            "amount",
            "amount_minor",
            "contained",
            "currency",
            "exposure",
            "refund",
            "recoverable",
            "remaining_exposure",
        }:
            raise AnalysisFinancialOutputError(
                f"proposal parameter {key_name} is not accepted at the advisory boundary"
            )
        if isinstance(item, Mapping):
            _validate_safe_parameters(item)
        elif isinstance(item, Sequence) and not isinstance(item, str | bytes):
            for nested in item:
                if isinstance(nested, Mapping):
                    _validate_safe_parameters(nested)
                elif not _safe_scalar(nested):
                    raise ProposalBoundaryError("proposal parameters must be JSON-compatible")
        elif not _safe_scalar(item):
            raise ProposalBoundaryError("proposal parameters must be JSON-compatible")


def _safe_scalar(value: Any) -> bool:
    return value is None or (
        isinstance(value, str | int | float | bool)
        and (not isinstance(value, float) or math.isfinite(value))
    )


def _references(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise AnalysisReferenceError(f"{name} references must be a sequence")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise AnalysisReferenceError(f"{name} references contain an invalid identity")
        result.append(item.strip())
    return tuple(sorted(set(result)))


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProposalBoundaryError(f"{name} is required")
    return value.strip()


def _normalized_name(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _forbidden_key(value: str) -> bool:
    return value in _FORBIDDEN_KEY_PARTS or any(part in value for part in _FORBIDDEN_KEY_PARTS)


def _forbidden_operation(value: str) -> bool:
    normalized = _normalized_name(value)
    return any(part in normalized for part in _FORBIDDEN_OPERATION_PARTS) or any(
        pattern.search(value) for pattern in _FORBIDDEN_STRING_PATTERNS
    )


TypedProposalParser = TypedProposalBoundary
ProposalBuilder = TypedProposalBoundary


__all__ = [
    "ForbiddenProposalError",
    "PROPOSAL_BOUNDARY_VERSION",
    "ProposalAuditRecord",
    "ProposalBoundaryAudit",
    "ProposalBoundaryError",
    "ProposalBoundaryResult",
    "ProposalBuilder",
    "TypedProposalBoundary",
    "TypedProposalParser",
    "build_typed_proposals",
    "construct_typed_proposals",
    "find_forbidden_operation",
]

# Stable public alias used by audit-oriented callers.
ProposalAuditRecord = ProposalBoundaryAudit
