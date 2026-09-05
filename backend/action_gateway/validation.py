"""Positive validation at the sole merchant-mutation boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.auth.oidc import IdentityType, TenantAuthorizationContext
from packages.contracts.action_gateway import ActionGatewayRequest
from packages.contracts.analysis_policy import ActionType, Approval, PolicyDecision, PolicyResult
from packages.contracts.connectors import ConnectorManifest, ConnectorType

from .controls import TenantActionControls

_ACTION_RESOURCE_OPERATION: dict[str, tuple[str, str, str]] = {
    ActionType.REVOKE_SUSPICIOUS_SESSION.value: (
        "sessions",
        "revoke_suspicious_session",
        "session-actions",
    ),
    ActionType.HOLD_FULFILLMENT.value: (
        "fulfillment",
        "hold_fulfillment",
        "fulfillment-actions",
    ),
}
_PARAMETERS: dict[str, frozenset[str]] = {
    ActionType.REVOKE_SUSPICIOUS_SESSION.value: frozenset({"reason"}),
    ActionType.HOLD_FULFILLMENT.value: frozenset({"reason", "hold_code"}),
}
_FORBIDDEN_NAMES = frozenset(
    {
        "url",
        "uri",
        "host",
        "http",
        "https",
        "shell",
        "command",
        "sql",
        "query",
        "filesystem",
        "path",
        "credential",
        "secret",
        "token",
        "destination",
        "network",
    }
)


class ActionGatewayValidationError(ValueError):
    """Raised when a request is not positively authorized for gateway use."""


@dataclass(frozen=True, slots=True)
class GatewayValidationResult:
    valid: bool
    reasons: tuple[str, ...]
    request: ActionGatewayRequest | None = None

    @property
    def accepted(self) -> bool:
        return self.valid

    def require_valid(self) -> ActionGatewayRequest:
        if not self.valid or self.request is None:
            raise ActionGatewayValidationError(
                "; ".join(self.reasons) or "gateway request is invalid"
            )
        return self.request


def validate_gateway_request(
    request: ActionGatewayRequest | object,
    *,
    manifest: ConnectorManifest | None = None,
    policy_decision: PolicyDecision | None = None,
    approval: Approval | None = None,
    authoritative_resource: object | Mapping[str, Any] | None = None,
    authorization_context: TenantAuthorizationContext | None = None,
    tenant_controls: TenantActionControls | None = None,
) -> GatewayValidationResult:
    reasons: list[str] = []
    if not isinstance(request, ActionGatewayRequest):
        return GatewayValidationResult(False, ("request must be an ActionGatewayRequest",))
    if authorization_context is None:
        reasons.append("authenticated Action Gateway service identity is required")
    else:
        if authorization_context.tenant_id != request.tenant_id:
            reasons.append("request crosses authenticated tenant scope")
        if authorization_context.identity_type is not IdentityType.SERVICE:
            reasons.append("only the Action Gateway service identity may submit mutation requests")
        elif "service" not in authorization_context.roles:
            reasons.append("Action Gateway service role is required")
    if manifest is None or not isinstance(manifest, ConnectorManifest):
        reasons.append("an allowlisted action connector manifest is required")
    else:
        if manifest.connector_type is not ConnectorType.ACTION:
            reasons.append("connector manifest is not an action connector")
        if manifest.tenant_id != request.tenant_id or manifest.connector_id != request.connector_id:
            reasons.append("connector manifest crosses tenant or connector scope")
        if request.operation not in manifest.operations:
            reasons.append("connector operation is not allowlisted")
        if manifest.mode.value not in {"live", "simulator"}:
            reasons.append("connector mode is unsupported")
        elif manifest.mode.value == "live":
            reasons.append("live action connector is not qualified")
        if tenant_controls is None:
            reasons.append("tenant action controls are required")
        elif isinstance(tenant_controls, TenantActionControls):
            reasons.extend(tenant_controls.reasons_for(request, manifest=manifest))
        else:
            reasons.append("tenant action controls are malformed")
    action_key = request.action_type.value
    expected = _ACTION_RESOURCE_OPERATION.get(action_key)
    if expected is None:
        reasons.append("action type is unsupported at the gateway boundary")
    else:
        resource_type, operation, connector_id = expected
        if request.operation != operation:
            reasons.append("operation does not match the typed action")
        if request.connector_id != connector_id:
            reasons.append("connector is not the allowlisted connector for the action")
        resource = _values(authoritative_resource)
        if resource:
            if (
                resource.get("tenant_id") != request.tenant_id
                or resource.get("case_id") != request.case_id
            ):
                reasons.append("authoritative resource crosses tenant or case scope")
            if resource.get("resource_id", resource.get("id")) != request.target_resource:
                reasons.append("target is not the authoritative resource")
            if resource.get("resource_type", resource_type) != resource_type:
                reasons.append("authoritative resource type is incompatible")
            if (
                request.action_type is ActionType.REVOKE_SUSPICIOUS_SESSION
                and resource.get("state") != "active"
            ):
                reasons.append("suspicious session is not active")
        else:
            reasons.append("authoritative resource state is required")
    if policy_decision is None or not isinstance(policy_decision, PolicyDecision):
        reasons.append("applicable policy decision is required")
    else:
        if (
            policy_decision.tenant_id != request.tenant_id
            or policy_decision.case_id != request.case_id
            or policy_decision.proposal_id != request.proposal_id
        ):
            reasons.append("policy decision does not match tenant, case, and proposal")
        if policy_decision.policy_version_id != request.policy_version_id:
            reasons.append("policy decision does not match policy version")
        if policy_decision.result not in {PolicyResult.ALLOW, PolicyResult.APPROVAL_REQUIRED}:
            reasons.append("policy result cannot authorize gateway submission")
        if policy_decision.result is PolicyResult.APPROVAL_REQUIRED:
            if approval is None:
                reasons.append("approval is required for this gateway request")
            else:
                _check_approval(approval, request, reasons)
        elif approval is not None:
            _check_approval(approval, request, reasons)
    allowed_parameters = _PARAMETERS.get(action_key, frozenset())
    if not isinstance(request.parameters, Mapping):
        reasons.append("action parameters must be an object")
    else:
        keys = set(request.parameters)
        if not keys.issubset(allowed_parameters):
            reasons.append("action parameters contain an unsupported capability")
        if any(_forbidden_name(str(key)) for key in keys):
            reasons.append(
                "action parameters contain a forbidden network, command, or credential field"
            )
        for key in allowed_parameters.intersection(keys):
            if not isinstance(request.parameters[key], str) or not request.parameters[key].strip():
                reasons.append(f"action parameter {key!r} must be non-empty text")
    if not request.request_checksum.strip():
        reasons.append("request checksum is required")
    return GatewayValidationResult(
        not reasons, tuple(sorted(set(reasons))), request if not reasons else None
    )


def assert_valid_gateway_request(*args: Any, **kwargs: Any) -> ActionGatewayRequest:
    return validate_gateway_request(*args, **kwargs).require_valid()


validate_action_request = validate_gateway_request


def _check_approval(approval: Approval, request: ActionGatewayRequest, reasons: list[str]) -> None:
    if (
        approval.tenant_id != request.tenant_id
        or approval.case_id != request.case_id
        or approval.proposal_id != request.proposal_id
    ):
        reasons.append("approval does not match gateway scope")
    if approval.policy_version_id != request.policy_version_id:
        reasons.append("approval does not match gateway policy version")
    if request.approval_id != approval.approval_id:
        reasons.append("gateway request does not carry the authoritative approval identity")
    if approval.status.value != "approved":
        reasons.append("approval is not active")
    if approval.approver_role != "approver":
        reasons.append("approval does not carry the required approver role")
    if approval.approved_at > request.requested_at:
        reasons.append("approval is not effective at the requested time")
    if approval.expires_at is not None and approval.expires_at <= request.requested_at:
        reasons.append("approval has expired at the requested time")
    if approval.scope != f"{request.action_type.value}:{request.target_resource}":
        reasons.append("approval does not match the exact action scope")
    if approval.approver_id == approval.proposer_id:
        reasons.append("approval violates separation of duties")


def _values(value: object | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return dict(asdict(value))
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _forbidden_name(value: str) -> bool:
    lowered = value.lower()
    return any(name in lowered for name in _FORBIDDEN_NAMES)


__all__ = [
    "ActionGatewayValidationError",
    "GatewayValidationResult",
    "assert_valid_gateway_request",
    "validate_action_request",
    "validate_gateway_request",
]
