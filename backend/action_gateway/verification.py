"""Independent merchant-state verification after Action Gateway execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from escalation.service import EscalationRecord, EscalationService
from packages.contracts.action_gateway import (
    ActionExecutionState,
    ActionGatewayRequest,
    VerificationResponse,
    VerificationResult,
)


class VerificationError(ValueError):
    """Raised when post-action state cannot be safely verified."""


class MerchantStateVerifier(Protocol):
    def observe(self, request: ActionGatewayRequest) -> Any: ...


@dataclass(frozen=True, slots=True)
class VerificationRouteResult:
    verification: VerificationResponse
    terminal_state: str | None
    escalation: EscalationRecord | None = None


@dataclass(frozen=True, slots=True)
class VerificationService:
    """Read merchant-controlled state and classify it independently."""

    verifier: MerchantStateVerifier
    repository: Any | None = None
    escalation_service: EscalationService | None = None

    def verify(
        self,
        *,
        request: ActionGatewayRequest,
        execution: Any,
        evidence_references: tuple[str, ...] = (),
        verification_id: str | None = None,
        method: str = "merchant_state_read",
        version: str = "verification-v1.0.0",
        observed_at: datetime | None = None,
    ) -> VerificationRouteResult:
        if _field(execution, "tenant_id") != request.tenant_id:
            raise VerificationError("execution crosses tenant scope")
        if _field(execution, "case_id") != request.case_id:
            raise VerificationError("execution crosses case scope")
        if _field(execution, "connector_id") != request.connector_id:
            raise VerificationError("execution connector does not match request")
        if _field(execution, "target_resource") != request.target_resource:
            raise VerificationError("execution target does not match request")
        canonical = _field(execution, "canonical_action_id")
        if canonical is not None and canonical != request.idempotency_key:
            raise VerificationError("verification action identity does not match execution")
        execution_status = _field(execution, "status")
        if execution_status in {
            ActionExecutionState.NOT_STARTED,
            ActionExecutionState.RECEIVED,
            ActionExecutionState.VALIDATED,
            ActionExecutionState.NOT_STARTED.value,
            ActionExecutionState.RECEIVED.value,
            ActionExecutionState.VALIDATED.value,
        }:
            raise VerificationError("execution is not eligible for post-action verification")
        if execution_status in {
            ActionExecutionState.UNKNOWN,
            ActionExecutionState.RECONCILING,
            ActionExecutionState.UNKNOWN.value,
            ActionExecutionState.RECONCILING.value,
        }:
            observed = {"state": "unknown", "verification": "inconclusive"}
        else:
            observed = self._observe(request)
        result = _classify(request.operation, observed)
        observed_state = _observed_state(observed)
        when = _utc(observed_at or datetime.now(UTC))
        execution_id = _field(execution, "execution_id")
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise VerificationError("execution identity is required for verification")
        verification = VerificationResponse(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            verification_id=verification_id or _verification_id(request, execution, observed_state),
            execution_id=execution_id,
            observed_resource_state=observed_state,
            verifier_source=str(observed.get("source") or "merchant-state-verifier"),
            result=result,
            evidence_references=tuple(evidence_references),
            verified_at=when,
            verification_method=method,
            verification_version=version,
            state_checksum=_state_checksum(observed),
            canonical_action_id=canonical or request.idempotency_key,
            connector_id=request.connector_id,
            resource_type=_field(execution, "resource_type") or _resource_type(request.operation),
            target_resource=request.target_resource,
        )
        if self.repository is not None:
            self.repository.create(
                verification_id=verification.verification_id,
                execution_id=verification.execution_id,
                case_id=request.case_id,
                canonical_action_id=canonical or request.idempotency_key,
                connector_id=verification.connector_id,
                resource_type=_field(execution, "resource_type")
                or _resource_type(request.operation),
                target_resource=request.target_resource,
                observed_resource_state=verification.observed_resource_state,
                verifier_source=verification.verifier_source,
                verification_method=method,
                verification_version=version,
                result=verification.result.value,
                evidence_references=verification.evidence_references,
                state_checksum=_state_checksum(observed),
                verified_at=verification.verified_at,
            )
        if result is VerificationResult.VERIFIED_SUCCESS:
            return VerificationRouteResult(verification, "verified_contained")
        if result is VerificationResult.VERIFIED_FAILURE:
            return VerificationRouteResult(verification, "verified_failed")
        return VerificationRouteResult(verification, None)

    def _observe(self, request: ActionGatewayRequest) -> dict[str, Any]:
        observer = getattr(self.verifier, "observe", None)
        if not callable(observer):
            observer = getattr(self.verifier, "read_state", None)
        if not callable(observer):
            raise VerificationError("merchant verifier must expose observe or read_state")
        value = observer(request)
        if isinstance(value, Mapping):
            observed = dict(value)
            for name, expected in (
                ("tenant_id", request.tenant_id),
                ("case_id", request.case_id),
                ("connector_id", request.connector_id),
                ("target_resource", request.target_resource),
                ("resource_id", request.target_resource),
            ):
                if name in observed and observed[name] != expected:
                    raise VerificationError(f"merchant observation {name} does not match request")
            return observed
        if isinstance(value, str):
            return {"state": value}
        raise VerificationError("merchant verifier returned an invalid state")


def verify_and_route(
    *,
    verification: VerificationResponse,
    escalation_owner: str,
    remaining_exposure_minor: int,
    currency: str,
    evidence_references: tuple[str, ...],
    recommended_human_decision: str,
    case_id: str | None = None,
    canonical_action_id: str | None = None,
    policy_version_id: str | None = None,
    escalation_service: EscalationService | None = None,
    owner_tenant_id: str | None = None,
) -> VerificationRouteResult:
    """Map a verified result to an explicit outcome; inconclusive escalates."""

    if not isinstance(verification, VerificationResponse):
        raise VerificationError("verification must be a VerificationResponse")
    if verification.result is not VerificationResult.INCONCLUSIVE:
        terminal = (
            "verified_contained"
            if verification.result is VerificationResult.VERIFIED_SUCCESS
            else "verified_failed"
        )
        return VerificationRouteResult(verification, terminal)
    if not escalation_owner.strip():
        raise VerificationError("inconclusive verification requires an escalation owner")
    if isinstance(remaining_exposure_minor, bool) or remaining_exposure_minor < 0:
        raise VerificationError("remaining exposure must be a non-negative integer")
    escalation_factory = escalation_service or EscalationService()
    escalation = escalation_factory.create(
        tenant_id=verification.tenant_id,
        case_id=case_id or verification.execution_id,
        owner_id=escalation_owner,
        owner_tenant_id=owner_tenant_id or verification.tenant_id,
        reason="merchant state could not be conclusively verified",
        evidence_references=tuple(evidence_references) or verification.evidence_references,
        remaining_exposure_minor=remaining_exposure_minor,
        currency=currency,
        recommended_human_decision=recommended_human_decision,
        canonical_action_id=canonical_action_id,
        execution_id=verification.execution_id,
        verification_id=verification.verification_id,
        policy_version_id=policy_version_id,
        correlation_id=verification.correlation_id,
    )
    return VerificationRouteResult(verification, "escalated_unresolved", escalation)


def _classify(operation: str, observed: Mapping[str, Any]) -> VerificationResult:
    explicit = observed.get("verification") or observed.get("result")
    if isinstance(explicit, VerificationResult):
        return explicit
    if isinstance(explicit, str):
        try:
            return VerificationResult(explicit)
        except ValueError:
            pass
    state = _observed_state(observed).lower()
    expected = "revoked" if operation == "revoke_suspicious_session" else "held"
    if state == expected or observed.get("contained") is True:
        return VerificationResult.VERIFIED_SUCCESS
    if state in {"active", "open", "available", "not_held", "failed", "rejected"}:
        return VerificationResult.VERIFIED_FAILURE
    return VerificationResult.INCONCLUSIVE


def _observed_state(value: Mapping[str, Any]) -> str:
    state = value.get("state") or value.get("observed_resource_state")
    return state.strip() if isinstance(state, str) and state.strip() else "not_observed"


def _resource_type(operation: str) -> str:
    return "sessions" if operation == "revoke_suspicious_session" else "fulfillment"


def _verification_id(request: ActionGatewayRequest, execution: Any, state: str) -> str:
    raw = (
        f"{request.tenant_id}:{_field(execution, 'execution_id')}"
        f":{request.target_resource}:{state}"
    )
    return "verification:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _state_checksum(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise VerificationError("verification time must include timezone")
    return value.astimezone(UTC)


__all__ = [
    "MerchantStateVerifier",
    "VerificationError",
    "VerificationRouteResult",
    "VerificationService",
    "verify_and_route",
]
