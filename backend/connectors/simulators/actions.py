"""Deterministic replay simulator for allowlisted defensive actions."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from packages.contracts.connectors import (
    ActionConnectorRequest,
    ActionConnectorResponse,
    ActionConnectorResult,
    ConnectorFailureState,
    ConnectorManifest,
    ConnectorMode,
    ConnectorType,
)

from connectors.actions.manifests import (
    build_fulfillment_action_manifest,
    build_session_action_manifest,
)


class ActionSimulatorScenario(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


_ALLOWED_PARAMETERS = {
    "revoke_suspicious_session": frozenset({"reason"}),
    "hold_fulfillment": frozenset({"reason", "hold_code"}),
}
_RESOURCE_STATE = {
    "sessions": frozenset({"active"}),
    "fulfillment": frozenset({"ready", "authorized", "unfulfilled", "pending"}),
}


class DeterministicActionSimulator:
    """Implement the action connector contract without arbitrary remote access."""

    def __init__(
        self,
        manifest: ConnectorManifest | None = None,
        *,
        tenant_id: str | None = None,
        scenario: ActionSimulatorScenario | str = ActionSimulatorScenario.COMPLETED,
        outcomes: Mapping[str, ActionSimulatorScenario | str]
        | Sequence[ActionSimulatorScenario | str]
        | None = None,
        resource_states: Mapping[str, str] | None = None,
        seed: str = "reclaim-action-simulator-v1",
    ) -> None:
        if manifest is None:
            if not tenant_id:
                raise ValueError("action simulator requires a tenant-scoped manifest")
            manifest = build_session_action_manifest(tenant_id)
        if (
            manifest.connector_type is not ConnectorType.ACTION
            or manifest.mode is not ConnectorMode.SIMULATOR
        ):
            raise ValueError("action simulator requires a simulator action manifest")
        if len(manifest.resources) != 1 or len(manifest.operations) != 1:
            raise ValueError("one deterministic simulator must declare one action")
        self.manifest = manifest
        self.seed = _required_text(seed, "simulator seed")
        self.resource_states = dict(resource_states or {})
        self.scenario = _scenario(scenario)
        self._outcomes = outcomes
        self._sequence_index = 0
        self._responses: dict[str, ActionConnectorResponse] = {}

    @classmethod
    def for_operation(
        cls,
        tenant_id: str,
        operation: str,
        *,
        scenario: ActionSimulatorScenario | str = ActionSimulatorScenario.COMPLETED,
        **kwargs: Any,
    ) -> DeterministicActionSimulator:
        manifest = {
            "revoke_suspicious_session": build_session_action_manifest(tenant_id),
            "hold_fulfillment": build_fulfillment_action_manifest(tenant_id),
        }.get(operation)
        if manifest is None:
            raise ValueError("simulator operation is not allowlisted")
        return cls(manifest, scenario=scenario, **kwargs)

    def execute(
        self,
        request: ActionConnectorRequest,
        *,
        credentials: Mapping[str, Any] | None = None,
    ) -> ActionConnectorResponse:
        del credentials  # simulator never receives or needs secret material
        self._validate(request)
        existing = self._responses.get(request.idempotency_key)
        if existing is not None:
            return existing
        scenario = self._outcome_for(request)
        result = ActionConnectorResult(scenario.value)
        response = ActionConnectorResponse(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            case_id=request.case_id,
            proposal_id=request.proposal_id,
            connector_id=request.connector_id,
            operation=request.operation,
            result=result,
            remote_reference=(
                None
                if result in {ActionConnectorResult.REJECTED, ActionConnectorResult.FAILED}
                else self._remote_reference(request)
            ),
            idempotency_key=request.idempotency_key,
            attempt_count=1,
            completed_at=request.requested_at
            if result is ActionConnectorResult.COMPLETED
            else None,
            failure_state=(
                ConnectorFailureState.INVALID
                if result is ActionConnectorResult.REJECTED
                else ConnectorFailureState.UNAVAILABLE
                if result is ActionConnectorResult.FAILED
                else None
            ),
        )
        self._responses[request.idempotency_key] = response
        return response

    invoke = execute

    def reconcile(self, idempotency_key: str) -> str:
        """Read the simulator's durable remote result without invoking again."""

        response = self._responses.get(idempotency_key)
        if response is None:
            return "not_submitted"
        if response.result is ActionConnectorResult.UNKNOWN:
            return "not_submitted"
        return response.result.value

    def _validate(self, request: ActionConnectorRequest) -> None:
        if (
            request.tenant_id != self.manifest.tenant_id
            or request.connector_id != self.manifest.connector_id
        ):
            raise ValueError("action request crosses simulator tenant or connector scope")
        if request.operation != self.manifest.operations[0]:
            raise ValueError("action operation is not allowlisted by the simulator")
        resource_type = self.manifest.resources[0]
        allowed_parameters = _ALLOWED_PARAMETERS[request.operation]
        if not set(request.parameters).issubset(allowed_parameters):
            raise ValueError("action simulator parameters are outside the allowlist")
        if any(
            not isinstance(value, str) or not value.strip() for value in request.parameters.values()
        ):
            raise ValueError("action simulator parameters must be non-empty text")
        state = self.resource_states.get(request.target_resource)
        if state is not None and state not in _RESOURCE_STATE[resource_type]:
            raise ValueError("action target is not in an eligible authoritative state")

    def _outcome_for(self, request: ActionConnectorRequest) -> ActionSimulatorScenario:
        if isinstance(self._outcomes, Mapping):
            value = self._outcomes.get(
                f"{request.operation}:{request.target_resource}",
                self._outcomes.get(request.target_resource, self.scenario),
            )
            return _scenario(value)
        if isinstance(self._outcomes, Sequence) and not isinstance(
            self._outcomes, (str, bytes, bytearray)
        ):
            if self._sequence_index < len(self._outcomes):
                value = self._outcomes[self._sequence_index]
                self._sequence_index += 1
                return _scenario(value)
        return self.scenario

    def _remote_reference(self, request: ActionConnectorRequest) -> str:
        digest = hashlib.sha256(
            f"{self.seed}:{request.operation}:{request.target_resource}:{request.idempotency_key}".encode()
        ).hexdigest()[:24]
        return f"sim-{request.operation}:{digest}"


def _scenario(value: ActionSimulatorScenario | str) -> ActionSimulatorScenario:
    try:
        return ActionSimulatorScenario(value)
    except ValueError as exc:
        raise ValueError("unsupported action simulator outcome") from exc


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


__all__ = ["ActionSimulatorScenario", "DeterministicActionSimulator"]
