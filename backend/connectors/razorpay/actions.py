"""Razorpay Test Mode payment-action validation seam.

This module deliberately stops before a provider mutation.  It validates
authoritative payment facts and exposes a replay-safe adapter contract, while
live financial execution remains disabled unless separately wired with every
required control.  No model-supplied amount, currency, or destination is ever
used as authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from packages.contracts.connectors import (
    ActionConnectorRequest,
    ActionConnectorResponse,
    ActionConnectorResult,
    ConnectorFailureState,
    ConnectorLimits,
    ConnectorManifest,
    ConnectorMode,
    ConnectorType,
)

RAZORPAY_ACTION_CONNECTOR_ID = "razorpay-test-actions"
RAZORPAY_ACTION_CONTRACT_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class RefundValidationResult:
    allowed: bool
    reason: str
    tenant_id: str | None = None
    case_id: str | None = None
    payment_id: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    original_payment_source: str | None = None

    @property
    def valid(self) -> bool:
        return self.allowed


def validate_refund_action(action: Mapping[str, Any] | object) -> RefundValidationResult:
    """Validate a refund against captured-payment facts and the original source."""

    values = _values(action)
    reasons: list[str] = []
    tenant_id = _required(values.get("tenant_id"), "tenant")
    case_id = _required(values.get("case_id"), "case")
    payment_id = _required(values.get("payment_id") or values.get("target_resource"), "payment")
    if tenant_id is None:
        reasons.append("tenant binding is required")
    if case_id is None:
        reasons.append("case binding is required")
    if payment_id is None:
        reasons.append("authoritative payment binding is required")

    state = values.get("state")
    captured = values.get("captured")
    if state != "captured" or captured is False:
        reasons.append("refund requires a captured payment")
    if captured is not None and not isinstance(captured, bool):
        reasons.append("captured payment flag is malformed")

    amount = _minor(values.get("amount_minor"), "captured payment amount")
    reimbursed = _minor(values.get("reimbursed_minor", 0), "reimbursed amount")
    requested = _minor(values.get("requested_amount_minor"), "requested refund amount")
    if amount is None:
        reasons.append("captured payment amount is required")
    elif amount <= 0:
        reasons.append("captured payment amount must be positive")
    if reimbursed is None or (reimbursed is not None and reimbursed < 0):
        reasons.append("reimbursed amount is malformed")
    if requested is None or (requested is not None and requested <= 0):
        reasons.append("refund amount must be positive")
    if amount is not None and reimbursed is not None and reimbursed > amount:
        reasons.append("reimbursed amount exceeds captured amount")
    if amount is not None and reimbursed is not None and requested is not None:
        unreimbursed = amount - reimbursed
        if unreimbursed <= 0:
            reasons.append("payment is already fully reimbursed")
        elif requested > unreimbursed:
            reasons.append("refund exceeds unreimbursed amount")

    currency = values.get("currency")
    if (
        not isinstance(currency, str)
        or len(currency.strip()) != 3
        or not currency.strip().isalpha()
    ):
        reasons.append("explicit payment currency is required")
        normalized_currency = None
    else:
        normalized_currency = currency.strip().upper()
    requested_currency = values.get("requested_currency") or values.get("refund_currency")
    if requested_currency is not None and (
        not isinstance(requested_currency, str)
        or normalized_currency is None
        or requested_currency.strip().upper() != normalized_currency
    ):
        reasons.append("refund currency must match the captured payment currency")
    source = _required(
        values.get("original_payment_source") or values.get("payment_source"),
        "original payment source",
    )
    if source is None or source.lower() in {
        "unknown",
        "unknown_source",
        "unavailable",
        "attacker-controlled-account",
    }:
        reasons.append("original payment source is required and must be authoritative")
    destination = values.get("refund_destination")
    if destination is not None and destination != source:
        reasons.append("refund destination must be the original payment source")

    authoritative = _values(values.get("authoritative_payment") or values.get("payment"))
    if not authoritative:
        reasons.append("authoritative captured payment record is required")
    else:
        required_authority = ("state", "amount_minor", "reimbursed_minor", "currency")
        missing_authority = tuple(
            field for field in required_authority if field not in authoritative
        )
        if missing_authority:
            reasons.append(
                "authoritative payment record is missing "
                + ", ".join(missing_authority)
            )
        authority_source = authoritative.get("original_payment_source") or authoritative.get(
            "payment_source"
        )
        if not _required(authority_source, "authoritative payment source"):
            reasons.append("authoritative payment source is required")
        for field, expected in (
            ("tenant_id", tenant_id),
            ("case_id", case_id),
            ("payment_id", payment_id),
            ("currency", normalized_currency),
            ("amount_minor", amount),
            ("reimbursed_minor", reimbursed),
            ("payment_source", source),
        ):
            actual = authority_source if field == "payment_source" else authoritative.get(field)
            if (
                actual is not None
                and (
                    actual.upper()
                    if field == "currency" and isinstance(actual, str)
                    else actual
                )
                != expected
            ):
                reasons.append(f"authoritative payment {field} does not match the request")
        if authoritative.get("state") != "captured":
            reasons.append("authoritative payment is not captured")
        if authoritative.get("captured") is not None and authoritative.get("captured") is not True:
            reasons.append("authoritative payment capture flag is not valid")

    if not _required(values.get("policy_version_id"), "policy version"):
        reasons.append("applicable policy version is required")
    if not _required(values.get("proposal_id"), "proposal"):
        reasons.append("proposal binding is required")
    provider_mode = values.get("provider_mode", "test")
    if provider_mode != "test":
        reasons.append("only Razorpay Test Mode is supported")

    return RefundValidationResult(
        allowed=not reasons,
        reason="valid captured payment refund" if not reasons else "; ".join(sorted(set(reasons))),
        tenant_id=tenant_id,
        case_id=case_id,
        payment_id=payment_id,
        amount_minor=requested,
        currency=normalized_currency,
        original_payment_source=source,
    )


class RazorpayTestModeActionAdapter:
    """Typed replay adapter; it never sends an HTTP request."""

    def __init__(self, tenant_id: str, *, live_financial_actions_enabled: bool = False) -> None:
        self.tenant_id = _required(tenant_id, "tenant") or ""
        self.live_financial_actions_enabled = live_financial_actions_enabled
        self.manifest = build_razorpay_test_mode_action_manifest(
            self.tenant_id, mode=ConnectorMode.SIMULATOR
        )

    def execute(
        self,
        request: ActionConnectorRequest,
        *,
        credentials: Mapping[str, Any] | None = None,
    ) -> ActionConnectorResponse:
        del credentials
        if request.tenant_id != self.tenant_id:
            raise ValueError("Razorpay action request crosses tenant scope")
        if request.operation != "refund_payment":
            raise ValueError("Razorpay action adapter only supports refund_payment")
        return ActionConnectorResponse(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            case_id=request.case_id,
            proposal_id=request.proposal_id,
            connector_id=request.connector_id,
            operation=request.operation,
            result=ActionConnectorResult.REJECTED,
            idempotency_key=request.idempotency_key,
            failure_state=ConnectorFailureState.INVALID,
        )

    def refund(
        self,
        *,
        request: ActionConnectorRequest,
        payment: Mapping[str, Any],
        policy_allows: bool,
        approval_valid: bool,
        credentials: Mapping[str, Any] | None = None,
        verification_available: bool = False,
        settings: Settings | None = None,
    ) -> ActionConnectorResponse:
        """Return a deterministic rejection unless all live controls are explicit.

        Even when every flag is supplied this implementation has no provider
        client, so it returns a controlled rejection rather than pretending to
        have executed a financial side effect.
        """

        validation = validate_refund_action(
            {
                **dict(payment),
                "tenant_id": request.tenant_id,
                "case_id": request.case_id,
                "proposal_id": request.proposal_id,
                "policy_version_id": request.policy_version_id
                if hasattr(request, "policy_version_id")
                else "gateway-policy",
                "requested_amount_minor": request.parameters.get("requested_amount_minor"),
                "provider_mode": "test",
            }
        )
        enabled = self.live_financial_actions_enabled or bool(
            settings is not None and settings.live_financial_actions_enabled
        )
        controls_ready = bool(
            validation.allowed
            and enabled
            and policy_allows
            and approval_valid
            and credentials
            and verification_available
        )
        return ActionConnectorResponse(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            case_id=request.case_id,
            proposal_id=request.proposal_id,
            connector_id=request.connector_id,
            operation=request.operation,
            result=ActionConnectorResult.REJECTED,
            idempotency_key=request.idempotency_key,
            failure_state=(
                ConnectorFailureState.INVALID
                if not controls_ready
                else ConnectorFailureState.UNAVAILABLE
            ),
        )


RazorpayPaymentActionAdapter = RazorpayTestModeActionAdapter


def build_razorpay_test_mode_action_manifest(
    tenant_id: str,
    *,
    mode: ConnectorMode | str = ConnectorMode.SIMULATOR,
) -> ConnectorManifest:
    if ConnectorMode(mode) is not ConnectorMode.SIMULATOR:
        raise ValueError("Razorpay Test Mode action connector is not live-qualified")
    return ConnectorManifest(
        tenant_id=tenant_id,
        correlation_id=f"manifest:{RAZORPAY_ACTION_CONNECTOR_ID}:{tenant_id}",
        connector_id=RAZORPAY_ACTION_CONNECTOR_ID,
        contract_version=RAZORPAY_ACTION_CONTRACT_VERSION,
        connector_type=ConnectorType.ACTION,
        mode=mode,
        resources=("payments",),
        operations=("refund_payment",),
        auth_scope=(f"merchant:{tenant_id}:action:payments:refund:test",),
        request_schema="action.connector.request.v1",
        response_schema="action.connector.response.v1",
        limits=ConnectorLimits(timeout_seconds=30),
        timestamp_semantics="requested_at is explicit UTC",
        idempotency_behavior="canonical gateway identity is required",
        failure_states=tuple(ConnectorFailureState),
    )


def _values(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _required(value: object, name: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _minor(value: object, name: str) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


__all__ = [
    "RAZORPAY_ACTION_CONNECTOR_ID",
    "RefundValidationResult",
    "RazorpayPaymentActionAdapter",
    "RazorpayTestModeActionAdapter",
    "build_razorpay_test_mode_action_manifest",
    "validate_refund_action",
]
