"""Centrally bounded tenant policy customization.

Tenant configuration is a constrained input to policy publication.  It is not
an authorization mechanism and it cannot grant a connector, action, credential,
or live-financial capability outside the central safety envelope.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationContext

CENTRAL_POLICY_BOUNDS: dict[str, tuple[float, float]] = {
    "auto_revoke_confidence": (0.90, 0.99),
    "min_confidence": (0.90, 0.99),
}
CENTRAL_MAX_AMOUNT_MINOR = 10_000_000
CENTRAL_ACTION_ALLOWLIST = frozenset(
    {
        "revoke_suspicious_session",
        "hold_fulfillment",
        "cancel_order",
        "refund_payment",
        "restore_identity",
    }
)
SUPPORTED_THRESHOLD_KEYS = frozenset(
    (
        *CENTRAL_POLICY_BOUNDS,
        "max_amount_minor",
        "allowed_customer_impact_classes",
        "allowed_resource_states",
    )
)


@dataclass(frozen=True, slots=True)
class PolicyConfigurationValidation:
    accepted: bool
    tenant_id: str
    change: str
    reason: str
    audit_reference: str
    thresholds: Mapping[str, Any]
    action_allowlist: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.accepted


def validate_tenant_policy_configuration(
    *,
    tenant_id: str,
    change: str,
    thresholds: Mapping[str, Any] | object,
    actor_role: str | None = None,
    action_allowlist: Sequence[str] | None = None,
    authorization_context: TenantAuthorizationContext | None = None,
) -> PolicyConfigurationValidation:
    """Validate a proposed tenant change and return an auditable decision.

    The plain ``actor_role`` argument exists for deterministic offline checks.
    HTTP and workflow callers must provide ``authorization_context``; when it is
    provided, role and tenant claims are authoritative and the payload role is
    ignored.
    """

    tenant = _required_text(tenant_id, "tenant_id")
    change_name = _required_text(change, "change")
    reasons: list[str] = []
    if authorization_context is not None:
        if authorization_context.tenant_id != tenant:
            reasons.append("authenticated identity crosses tenant boundary")
        elif authorization_context.identity_type is not IdentityType.USER:
            reasons.append("service and model identities cannot change policy")
        elif str(RequiredRole.POLICY_OWNER) not in authorization_context.roles:
            reasons.append("policy-owner role is required")
    elif actor_role != RequiredRole.POLICY_OWNER.value:
        reasons.append("policy-owner role is required")

    if not isinstance(thresholds, Mapping):
        reasons.append("thresholds must be an object")
        normalized_thresholds: dict[str, Any] = {}
    else:
        normalized_thresholds = dict(thresholds)
        for key, value in normalized_thresholds.items():
            if key not in SUPPORTED_THRESHOLD_KEYS:
                reasons.append(f"threshold {key!r} is not centrally supported")
                continue
            bounds = CENTRAL_POLICY_BOUNDS.get(key)
            if bounds is not None and (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not bounds[0] <= float(value) <= bounds[1]
            ):
                reasons.append(f"threshold {key!r} is outside the central safety bound")
            if key == "max_amount_minor" and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= CENTRAL_MAX_AMOUNT_MINOR
            ):
                reasons.append("max_amount_minor is outside the central safety bound")

    normalized_actions = tuple(sorted(set(action_allowlist or ())))
    if any(not isinstance(action, str) or not action.strip() for action in normalized_actions):
        reasons.append("action allowlist is malformed")
    if not set(normalized_actions).issubset(CENTRAL_ACTION_ALLOWLIST):
        reasons.append("tenant action allowlist widens central capabilities")

    reason = "accepted" if not reasons else "; ".join(sorted(set(reasons)))
    audit_reference = (
        "policy-change:"
        + hashlib.sha256(
            json.dumps(
                {
                    "tenant_id": tenant,
                    "change": change_name,
                    "thresholds": normalized_thresholds,
                    "action_allowlist": normalized_actions,
                    "reason": reason,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
    )
    return PolicyConfigurationValidation(
        accepted=not reasons,
        tenant_id=tenant,
        change=change_name,
        reason=reason,
        audit_reference=audit_reference,
        thresholds=normalized_thresholds,
        action_allowlist=normalized_actions,
    )


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


__all__ = [
    "CENTRAL_ACTION_ALLOWLIST",
    "CENTRAL_MAX_AMOUNT_MINOR",
    "CENTRAL_POLICY_BOUNDS",
    "PolicyConfigurationValidation",
    "SUPPORTED_THRESHOLD_KEYS",
    "validate_tenant_policy_configuration",
]
