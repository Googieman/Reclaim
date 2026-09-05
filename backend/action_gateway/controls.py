"""Tenant-scoped controls for qualifying Action Gateway submissions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from packages.contracts.action_gateway import ActionGatewayRequest
from packages.contracts.analysis_policy import ActionType
from packages.contracts.connectors import ConnectorManifest, ConnectorMode

_ACTION_BY_OPERATION = {
    "revoke_suspicious_session": ActionType.REVOKE_SUSPICIOUS_SESSION.value,
    "hold_fulfillment": ActionType.HOLD_FULFILLMENT.value,
}
_KNOWN_ACTIONS = frozenset(item.value for item in ActionType)
_CENTRAL_MAX_AMOUNT_MINOR = 10_000_000


@dataclass(frozen=True, slots=True)
class TenantActionControls:
    """Immutable, fail-closed action controls for one tenant.

    The current release qualifies deterministic simulator connectors only.  Live
    action flags are intentionally rejected until an independently qualified
    executor and provider control plane exists.
    """

    tenant_id: str
    connector_allowlist: frozenset[str]
    action_allowlist: frozenset[str]
    max_parameter_bytes: int = 4_096
    max_amount_minor: int = _CENTRAL_MAX_AMOUNT_MINOR
    emergency_disabled: bool = False
    circuit_breaker_open: bool = False
    live_actions_enabled: bool = False
    live_financial_actions_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise ValueError("tenant action controls require tenant scope")
        if not isinstance(self.connector_allowlist, frozenset) or not isinstance(
            self.action_allowlist, frozenset
        ):
            raise ValueError("tenant action allowlists must be frozen sets")
        if any(
            not isinstance(value, str) or not value.strip()
            for values in (self.connector_allowlist, self.action_allowlist)
            for value in values
        ):
            raise ValueError("tenant action allowlists must contain non-blank identities")
        if not self.action_allowlist.issubset(_KNOWN_ACTIONS):
            raise ValueError("tenant action allowlist contains an unsupported action")
        if (
            isinstance(self.max_parameter_bytes, bool)
            or not isinstance(self.max_parameter_bytes, int)
            or not 1 <= self.max_parameter_bytes <= 1_048_576
        ):
            raise ValueError("tenant action parameter limit is outside the central bound")
        if (
            isinstance(self.max_amount_minor, bool)
            or not isinstance(self.max_amount_minor, int)
            or not 0 <= self.max_amount_minor <= _CENTRAL_MAX_AMOUNT_MINOR
        ):
            raise ValueError("tenant action amount limit is outside the central bound")
        if self.live_actions_enabled or self.live_financial_actions_enabled:
            raise ValueError("live actions are not qualified and must remain disabled")

    def reasons_for(
        self,
        request: ActionGatewayRequest,
        *,
        manifest: ConnectorManifest,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.tenant_id != request.tenant_id:
            reasons.append("tenant action controls cross request scope")
        if self.emergency_disabled:
            reasons.append("tenant emergency action disable is active")
        if self.circuit_breaker_open:
            reasons.append("tenant action circuit breaker is open")
        if request.connector_id not in self.connector_allowlist:
            reasons.append("connector is not allowlisted for this tenant")
        if request.action_type.value not in self.action_allowlist:
            reasons.append("action is not allowlisted for this tenant")
        if manifest.mode is not ConnectorMode.SIMULATOR:
            reasons.append("action connector is not qualified for execution")
        try:
            parameter_bytes = len(
                json.dumps(
                    request.parameters,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            reasons.append("action parameters are not JSON-compatible")
        else:
            if parameter_bytes > self.max_parameter_bytes:
                reasons.append("action parameters exceed the tenant limit")
        for name in ("amount_minor", "requested_amount_minor"):
            amount = request.parameters.get(name)
            if amount is None:
                continue
            if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
                reasons.append("action amount must be a non-negative integer")
            elif amount > self.max_amount_minor:
                reasons.append("action amount exceeds the tenant limit")
        return tuple(sorted(set(reasons)))


def controls_for_connectors(
    connectors: Mapping[str, Any],
) -> dict[str, TenantActionControls]:
    """Build safe defaults from tenant-bound simulator manifests."""

    grouped: dict[str, tuple[set[str], set[str]]] = {}
    for connector in connectors.values():
        manifest = getattr(connector, "manifest", None)
        tenant_id = getattr(manifest, "tenant_id", None)
        if not isinstance(manifest, ConnectorManifest) or not isinstance(tenant_id, str):
            continue
        connector_ids, actions = grouped.setdefault(tenant_id, (set(), set()))
        connector_ids.add(str(manifest.connector_id))
        actions.update(
            _ACTION_BY_OPERATION[operation]
            for operation in manifest.operations
            if operation in _ACTION_BY_OPERATION
        )
    return {
        tenant_id: TenantActionControls(
            tenant_id=tenant_id,
            connector_allowlist=frozenset(connector_ids),
            action_allowlist=frozenset(actions),
        )
        for tenant_id, (connector_ids, actions) in grouped.items()
    }


__all__ = ["TenantActionControls", "controls_for_connectors"]
