"""Deterministic policy evaluation for typed action proposals.

This module consumes authoritative snapshots and a published policy value.  It
does not call a model, connector, database, or network service.  Missing or
inconsistent authority is represented as an escalation when the identity
context is complete; callers without enough identity to construct a safe
decision receive a hard error.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from packages.contracts.analysis_policy import ActionType, PolicyDecision, PolicyResult

from .tenant_configuration import CENTRAL_MAX_AMOUNT_MINOR
from .versions import (
    PolicyPublicationStatus,
    PolicyScope,
    PolicyVersion,
    PolicyVersionError,
    verify_policy_checksum,
)

EVALUATOR_VERSION = "deterministic-policy-evaluator-v1.0.0"
_HIGH_IMPACT_ACTIONS = frozenset(
    {
        ActionType.CANCEL_ORDER.value,
        ActionType.REFUND_PAYMENT.value,
        ActionType.RESTORE_IDENTITY.value,
    }
)
_DEFAULT_RESOURCE_STATES: dict[str, frozenset[str]] = {
    ActionType.REVOKE_SUSPICIOUS_SESSION.value: frozenset({"active"}),
    ActionType.HOLD_FULFILLMENT.value: frozenset({"ready", "authorized", "unfulfilled", "pending"}),
    ActionType.CANCEL_ORDER.value: frozenset({"created", "pending", "confirmed"}),
    ActionType.REFUND_PAYMENT.value: frozenset({"captured"}),
    ActionType.RESTORE_IDENTITY.value: frozenset({"locked", "suspended"}),
}
_SUPPORTED_THRESHOLD_KEYS = frozenset(
    {
        "min_confidence",
        "auto_revoke_confidence",
        "max_amount_minor",
        "allowed_customer_impact_classes",
        "allowed_resource_states",
    }
)
_SUPPORTED_ACTIONS = frozenset(item.value for item in ActionType)


class PolicyEvaluationError(ValueError):
    """Raised when no safely scoped policy decision can be constructed."""


@dataclass(frozen=True, slots=True)
class PolicyEvaluationInput:
    """Named authoritative facts accepted by :func:`evaluate_policy`."""

    tenant_id: str
    case_id: str
    proposal_id: str
    correlation_id: str
    action: str
    confidence: float | None
    resource_state: str | None
    resource_id: str | None
    connector_id: str | None
    amount_minor: int | None
    currency: str | None
    is_reversible: bool | None
    customer_impact: Mapping[str, Any] | None
    approval: Mapping[str, Any] | None


def evaluate_policy(
    *,
    proposal: object | Mapping[str, Any] | None = None,
    policy_version: PolicyVersion | None = None,
    policy: PolicyVersion | None = None,
    tenant_id: str | None = None,
    case_id: str | None = None,
    proposal_id: str | None = None,
    correlation_id: str | None = None,
    action: str | None = None,
    confidence: float | None = None,
    resource: object | Mapping[str, Any] | None = None,
    authoritative_resource_state: object | Mapping[str, Any] | None = None,
    amount_minor: int | None = None,
    currency: str | None = None,
    reversibility: bool | None = None,
    is_reversible: bool | None = None,
    customer_impact: object | Mapping[str, Any] | None = None,
    approval: object | Mapping[str, Any] | None = None,
    approval_required: bool | None = None,
    evaluated_at: datetime | None = None,
    decision_id: str | None = None,
    evaluator_version: str = EVALUATOR_VERSION,
) -> PolicyDecision:
    """Evaluate one proposal against one immutable policy version.

    ``approval_required`` is accepted as a compatibility input only for
    recording the caller's authoritative approval state; it can never widen a
    policy.  The policy's own approval rules and high-impact defaults decide
    whether approval is needed.
    """

    policy_value = policy_version or policy
    if not isinstance(policy_value, PolicyVersion):
        raise PolicyEvaluationError("a validated PolicyVersion is required")
    try:
        verify_policy_checksum(policy_value)
    except PolicyVersionError as exc:
        raise PolicyEvaluationError(str(exc)) from exc

    proposal_values = _values(proposal)
    tenant = _text(tenant_id or proposal_values.get("tenant_id"))
    case = _text(case_id or proposal_values.get("case_id"))
    proposal_key = _text(proposal_id or proposal_values.get("proposal_id"))
    correlation = _text(correlation_id or proposal_values.get("correlation_id"))
    selected_action = _text(
        action or proposal_values.get("action_type") or proposal_values.get("action")
    )
    input_values = _build_input(
        tenant=tenant,
        case=case,
        proposal_id=proposal_key,
        correlation=correlation,
        action=selected_action,
        proposal_values=proposal_values,
        confidence=confidence,
        resource=resource,
        authoritative_resource_state=authoritative_resource_state,
        amount_minor=amount_minor,
        currency=currency,
        reversibility=reversibility,
        is_reversible=is_reversible,
        customer_impact=customer_impact,
        approval=approval,
    )
    now = _utc(evaluated_at or datetime.now(UTC), "evaluation time")
    reasons: list[str] = []

    if policy_value.scope_type is PolicyScope.TENANT and policy_value.tenant_id != tenant:
        reasons.append("policy version crosses tenant boundary")
    if policy_value.publication_status is not PolicyPublicationStatus.PUBLISHED:
        reasons.append("policy version is not published")
    elif not policy_value.is_effective(now):
        reasons.append("policy version is stale or outside its effective interval")
    reasons.extend(_input_errors(input_values))

    thresholds = _mapping(policy_value.thresholds, "policy thresholds", reasons)
    approval_rules = _mapping(policy_value.approval_rules, "policy approval rules", reasons)
    unknown_thresholds = set(thresholds) - _SUPPORTED_THRESHOLD_KEYS
    if unknown_thresholds:
        reasons.append("policy contains unsupported conditions")
    unknown_approval_rules = set(approval_rules) - _SUPPORTED_ACTIONS
    if unknown_approval_rules:
        reasons.append("policy contains unsupported approval conditions")
    if any(
        not isinstance(value, (bool, str))
        or (
            isinstance(value, str)
            and value not in {"required", "approval", "approval_required", "none", "not_required"}
        )
        for value in approval_rules.values()
    ):
        reasons.append("policy approval conditions are malformed")
    allowlist = policy_value.action_allowlist
    if selected_action not in allowlist:
        reasons.append("action is not allowlisted by the policy")

    decision_result = PolicyResult.ESCALATE
    if not reasons:
        minimum_confidence = _number(
            thresholds.get("min_confidence", thresholds.get("auto_revoke_confidence", 0)),
            "confidence threshold",
            reasons,
        )
        if input_values.confidence is None or minimum_confidence is None:
            reasons.append("confidence threshold is unavailable")
        elif input_values.confidence < minimum_confidence:
            decision_result = PolicyResult.DENY
            reasons.append("confidence is below the policy threshold")

        _check_amount(input_values, thresholds, reasons)
        _check_resource_state(input_values, thresholds, reasons)
        _check_customer_impact(input_values, thresholds, reasons)

        if reasons:
            if any(
                "malformed" in reason or "unavailable" in reason or "boundary" in reason
                for reason in reasons
            ):
                decision_result = PolicyResult.ESCALATE
            elif decision_result is not PolicyResult.DENY:
                decision_result = PolicyResult.DENY
        else:
            required = _requires_approval(
                action=selected_action,
                policy_rules=approval_rules,
                is_reversible=input_values.is_reversible,
                explicit=approval_required,
            )
            if required and not _approval_is_current(
                input_values.approval,
                policy_value.policy_version_id,
                now,
            ):
                decision_result = PolicyResult.APPROVAL_REQUIRED
            else:
                decision_result = PolicyResult.ALLOW

    evaluated_conditions = {
        "permission": {
            "action": selected_action,
            "operation": _text_or_none(proposal_values.get("operation")) or selected_action,
            "allowed": selected_action in allowlist,
        },
        "confidence": {
            "value": input_values.confidence,
            "threshold": thresholds.get("min_confidence", thresholds.get("auto_revoke_confidence")),
        },
        "authoritative_resource_state": {
            "resource_id": input_values.resource_id,
            "resource_state": input_values.resource_state,
            "connector_id": input_values.connector_id,
        },
        "amount": {"minor": input_values.amount_minor, "currency": input_values.currency},
        "reversibility": {"is_reversible": input_values.is_reversible},
        "customer_impact": dict(input_values.customer_impact or {}),
        "approval": {
            "required": _requires_approval(
                action=selected_action,
                policy_rules=approval_rules,
                is_reversible=input_values.is_reversible,
                explicit=approval_required,
            ),
            "state": _approval_state(input_values.approval),
        },
        "policy_version": policy_value.policy_version_id,
        "policy_checksum": policy_value.immutable_checksum,
        "effective_interval": {
            "from": policy_value.effective_from.isoformat(),
            "to": None
            if policy_value.effective_to is None
            else policy_value.effective_to.isoformat(),
        },
        "schema_version": policy_value.schema_version,
        "provenance": {"correlation_id": correlation},
        "failure_reasons": tuple(sorted(set(reasons))),
    }
    identity_payload = {
        "tenant_id": tenant,
        "case_id": case,
        "proposal_id": proposal_key,
        "policy_version_id": policy_value.policy_version_id,
        "evaluated_conditions": evaluated_conditions,
        "evaluator_version": evaluator_version,
    }
    stable_id = (
        decision_id
        or hashlib.sha256(
            json.dumps(
                identity_payload, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()
    )
    return PolicyDecision(
        tenant_id=tenant,
        correlation_id=correlation,
        decision_id=stable_id,
        case_id=case,
        proposal_id=proposal_key,
        policy_version_id=policy_value.policy_version_id,
        result=decision_result,
        evaluated_conditions=evaluated_conditions,
        evaluator_version=evaluator_version,
        decided_at=now,
    )


def _values(value: object | Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return dict(asdict(value))
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyEvaluationError("policy evaluation identity is incomplete")
    return value.strip()


def _text_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PolicyEvaluationError(f"{name} must include an explicit timezone")
    return value.astimezone(UTC)


def _mapping(value: object, name: str, reasons: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        reasons.append(f"{name} is malformed")
        return {}
    return value


def _build_input(
    *,
    tenant: str,
    case: str,
    proposal_id: str,
    correlation: str,
    action: str,
    proposal_values: Mapping[str, Any],
    confidence: float | None,
    resource: object | Mapping[str, Any] | None,
    authoritative_resource_state: object | Mapping[str, Any] | None,
    amount_minor: int | None,
    currency: str | None,
    reversibility: bool | None,
    is_reversible: bool | None,
    customer_impact: object | Mapping[str, Any] | None,
    approval: object | Mapping[str, Any] | None,
) -> PolicyEvaluationInput:
    resource_values = _values(resource) or _values(authoritative_resource_state)
    state_values = _values(authoritative_resource_state)
    if state_values:
        resource_values = {**resource_values, **state_values}
    proposal_amount = proposal_values.get("requested_amount_minor")
    selected_amount = amount_minor if amount_minor is not None else proposal_amount
    selected_currency = currency or _text_or_none(proposal_values.get("currency"))
    selected_confidence = confidence
    if selected_confidence is None and isinstance(proposal_values.get("confidence"), (int, float)):
        selected_confidence = float(proposal_values["confidence"])
    selected_reversible = is_reversible if is_reversible is not None else reversibility
    if selected_reversible is None and "is_reversible" in resource_values:
        selected_reversible = resource_values.get("is_reversible")
    impact = (
        customer_impact if customer_impact is not None else proposal_values.get("customer_impact")
    )
    approval_values = _values(approval)
    return PolicyEvaluationInput(
        tenant_id=tenant,
        case_id=case,
        proposal_id=proposal_id,
        correlation_id=correlation,
        action=action,
        confidence=selected_confidence,
        resource_state=_text_or_none(
            resource_values.get("state") or resource_values.get("resource_state")
        ),
        resource_id=_text_or_none(resource_values.get("resource_id") or resource_values.get("id")),
        connector_id=_text_or_none(resource_values.get("connector_id")),
        amount_minor=selected_amount,
        currency=selected_currency.upper() if isinstance(selected_currency, str) else None,
        is_reversible=selected_reversible if isinstance(selected_reversible, bool) else None,
        customer_impact=impact if isinstance(impact, Mapping) else None,
        approval=approval_values or None,
    )


def _input_errors(values: PolicyEvaluationInput) -> list[str]:
    errors: list[str] = []
    if not values.action:
        errors.append("action is missing")
    elif values.action not in _SUPPORTED_ACTIONS:
        errors.append("action is unsupported")
    if (
        values.confidence is None
        or isinstance(values.confidence, bool)
        or not 0 <= values.confidence <= 1
    ):
        errors.append("confidence is missing or malformed")
    if not values.resource_state or not values.resource_id or not values.connector_id:
        errors.append("authoritative resource state is missing or malformed")
    if values.amount_minor is None:
        errors.append("amount is missing")
    elif (
        isinstance(values.amount_minor, bool)
        or not isinstance(values.amount_minor, int)
        or values.amount_minor < 0
    ):
        errors.append("amount is malformed")
    if (
        values.amount_minor is not None
        and values.amount_minor > 0
        and (values.currency is None or len(values.currency) != 3 or not values.currency.isalpha())
    ):
        errors.append("currency is missing or malformed")
    if values.is_reversible is None:
        errors.append("reversibility is missing")
    if values.customer_impact is None:
        errors.append("customer impact is missing or malformed")
    return errors


def _number(value: object, name: str, reasons: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= float(value) <= 1:
        reasons.append(f"{name} is malformed")
        return None
    return float(value)


def _check_amount(
    values: PolicyEvaluationInput, thresholds: Mapping[str, Any], reasons: list[str]
) -> None:
    maximum = thresholds.get("max_amount_minor")
    if maximum is None or values.amount_minor is None:
        return
    if (
        isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or maximum < 0
        or maximum > CENTRAL_MAX_AMOUNT_MINOR
    ):
        reasons.append("maximum amount is malformed")
    elif values.amount_minor > maximum:
        reasons.append("amount exceeds policy bound")


def _check_resource_state(
    values: PolicyEvaluationInput, thresholds: Mapping[str, Any], reasons: list[str]
) -> None:
    allowed = thresholds.get("allowed_resource_states")
    states: object = _DEFAULT_RESOURCE_STATES.get(values.action, frozenset())
    if isinstance(allowed, Mapping):
        configured = allowed.get(values.action)
        if configured is not None:
            states = configured
    if not isinstance(states, (list, tuple, set, frozenset)) or not all(
        isinstance(item, str) for item in states
    ):
        reasons.append("resource state conditions are malformed")
    elif values.resource_state not in states:
        reasons.append("authoritative resource state is not eligible for this action")


def _check_customer_impact(
    values: PolicyEvaluationInput, thresholds: Mapping[str, Any], reasons: list[str]
) -> None:
    impact = values.customer_impact or {}
    impact_class = impact.get("class")
    allowed_classes = thresholds.get("allowed_customer_impact_classes")
    if allowed_classes is not None:
        if not isinstance(allowed_classes, (list, tuple, set, frozenset)) or not all(
            isinstance(item, str) for item in allowed_classes
        ):
            reasons.append("customer impact conditions are malformed")
        elif impact_class not in allowed_classes:
            reasons.append("customer impact is outside policy bounds")


def _requires_approval(
    *,
    action: str,
    policy_rules: Mapping[str, Any],
    is_reversible: bool | None,
    explicit: bool | None,
) -> bool:
    if explicit is True:
        return True
    configured = policy_rules.get(action)
    if configured is True or (
        isinstance(configured, str)
        and configured
        in {
            "required",
            "approval",
            "approval_required",
        }
    ):
        return True
    if configured is False or (
        isinstance(configured, str) and configured in {"none", "not_required"}
    ):
        return False
    if action in _HIGH_IMPACT_ACTIONS:
        return True
    return is_reversible is False


def _approval_is_current(
    approval: Mapping[str, Any] | None, policy_version_id: str, now: datetime
) -> bool:
    if not approval or str(approval.get("status", "")) != "approved":
        return False
    if approval.get("policy_version_id") != policy_version_id:
        return False
    approved_at = approval.get("approved_at")
    expires_at = approval.get("expires_at")
    if not isinstance(approved_at, datetime) or approved_at.tzinfo is None or approved_at > now:
        return False
    return not isinstance(expires_at, datetime) or (
        expires_at.tzinfo is not None and expires_at > now
    )


def _approval_state(approval: Mapping[str, Any] | None) -> str:
    if not approval:
        return "not_requested"
    return str(approval.get("status", "unknown"))


__all__ = ["EVALUATOR_VERSION", "PolicyEvaluationError", "PolicyEvaluationInput", "evaluate_policy"]
