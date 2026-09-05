"""The only runtime boundary allowed to invoke merchant mutation connectors."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from app.secrets.vault import SecretAccessDenied
from packages.contracts.action_gateway import (
    ActionExecutionState,
    ActionGatewayRequest,
    ActionGatewayResponse,
)
from packages.contracts.analysis_policy import Approval, PolicyDecision
from packages.contracts.connectors import (
    ActionConnectorResponse,
    ActionConnectorResult,
    ConnectorManifest,
)

from .controls import TenantActionControls, controls_for_connectors
from .idempotency import (
    ActionExecutionRecord,
    ActionIdempotencyError,
    ExecutionStore,
    derive_action_idempotency_key,
    require_matching_canonical_identity,
)
from .network_policy import ActionNetworkBoundary, NetworkPolicy, build_default_network_policy
from .state_machine import ActionGatewayStateMachine
from .validation import ActionGatewayValidationError, validate_gateway_request


class ActionGatewayError(RuntimeError):
    """Raised when a gateway submission cannot be safely executed."""


class ActionConnector(Protocol):
    manifest: ConnectorManifest

    def execute(
        self, request: Any, *, credentials: Mapping[str, Any] | None = None
    ) -> ActionConnectorResponse: ...


class ActionGateway:
    """Validate and invoke only an allowlisted, tenant-bound action connector."""

    def __init__(
        self,
        *,
        connectors: Mapping[str, ActionConnector] | None = None,
        secret_store: Any | None = None,
        network_policy: NetworkPolicy | None = None,
        audit_reference_factory: Any | None = None,
        execution_store: ExecutionStore | Any | None = None,
        tenant_controls: Mapping[str, TenantActionControls] | None = None,
    ) -> None:
        self._connectors = dict(connectors or {})
        self._tenant_controls = (
            controls_for_connectors(self._connectors)
            if tenant_controls is None
            else dict(tenant_controls)
        )
        self._secret_store = secret_store
        self._network = ActionNetworkBoundary(
            network_policy or build_default_network_policy(self._connectors)
        )
        self._audit_reference_factory = audit_reference_factory
        self._execution_store = execution_store

    @property
    def connector_ids(self) -> frozenset[str]:
        return frozenset(self._connectors)

    def validate(
        self,
        request: ActionGatewayRequest | object,
        *,
        policy_decision: PolicyDecision | None = None,
        approval: Approval | None = None,
        authoritative_resource: object | Mapping[str, Any] | None = None,
        authorization_context: Any | None = None,
    ) -> Any:
        connector_id = getattr(request, "connector_id", None)
        tenant_id = getattr(request, "tenant_id", None)
        connector = self._connectors.get(connector_id) if isinstance(connector_id, str) else None
        return validate_gateway_request(
            request,
            manifest=None if connector is None else connector.manifest,
            policy_decision=policy_decision,
            approval=approval,
            authoritative_resource=authoritative_resource,
            authorization_context=authorization_context,
            tenant_controls=self._tenant_controls.get(tenant_id),
        )

    def submit(
        self,
        request: ActionGatewayRequest,
        *,
        policy_decision: PolicyDecision | None = None,
        approval: Approval | None = None,
        authoritative_resource: object | Mapping[str, Any] | None = None,
        authorization_context: Any | None = None,
        canonical_action_id: str | None = None,
        execution_store: ExecutionStore | Any | None = None,
    ) -> ActionGatewayResponse:
        validation = self.validate(
            request,
            policy_decision=policy_decision,
            approval=approval,
            authoritative_resource=authoritative_resource,
            authorization_context=authorization_context,
        )
        try:
            validation.require_valid()
        except ActionGatewayValidationError as exc:
            raise ActionGatewayError(str(exc)) from exc

        store = execution_store or self._execution_store
        record: ActionExecutionRecord | None = None
        if store is not None:
            canonical = canonical_action_id or _derive_request_identity(
                request, authoritative_resource
            )
            try:
                canonical = require_matching_canonical_identity(
                    request, canonical_action_id=canonical
                )
                resource_values = _values(authoritative_resource)
                resource_type = str(resource_values.get("resource_type") or "")
                if not resource_type:
                    raise ActionIdempotencyError("authoritative resource type is required")
                record, inserted = store.begin(
                    request=request,
                    canonical_action_id=canonical,
                    resource_type=resource_type,
                    policy_decision_id=policy_decision.decision_id
                    if policy_decision is not None
                    else "",
                    approval_id=None if approval is None else approval.approval_id,
                )
            except (ActionIdempotencyError, ValueError, KeyError) as exc:
                raise ActionGatewayError(str(exc)) from exc
            if not inserted:
                return _response_from_record(record)
            record = _store_mark_validated(store, record)

        connector = self._connectors[request.connector_id]
        self._network.authorize_connector(request.connector_id)
        credentials = (
            self._credentials(request.tenant_id, request.connector_id)
            if connector.manifest.mode.value == "live"
            else None
        )
        try:
            response = connector.execute(request, credentials=credentials)
        except Exception as exc:
            if record is None:
                raise ActionGatewayError("action connector result is unknown") from exc
            record = _store_mark_unknown(
                store, record, result_reference=self._audit_reference_for_unknown(request)
            )
            return ActionGatewayResponse(
                tenant_id=request.tenant_id,
                correlation_id=request.correlation_id,
                execution_id=record.execution_id,
                proposal_id=request.proposal_id,
                state=ActionExecutionState.UNKNOWN,
                connector_result="unknown",
                idempotency_key=request.idempotency_key,
                reconciliation_required=True,
                verification_required=True,
                audit_reference=self._audit_reference_for_unknown(request),
            )
        invalid_response_reason: str | None = None
        if not isinstance(response, ActionConnectorResponse):
            invalid_response_reason = "action connector returned an invalid response contract"
        elif (
            response.tenant_id != request.tenant_id
            or response.case_id != request.case_id
            or response.proposal_id != request.proposal_id
            or response.correlation_id != request.correlation_id
        ):
            invalid_response_reason = "action connector response crossed gateway scope"
        elif (
            response.connector_id != request.connector_id
            or response.operation != request.operation
        ):
            invalid_response_reason = "action connector response identity does not match request"
        elif response.idempotency_key != request.idempotency_key:
            invalid_response_reason = (
                "action connector response identity does not match idempotency"
            )
        if invalid_response_reason is not None:
            if record is None:
                raise ActionGatewayError("action connector result is unknown")
            record = _store_mark_unknown(
                store,
                record,
                result_reference=self._audit_reference_for_unknown(request),
            )
            return ActionGatewayResponse(
                tenant_id=request.tenant_id,
                correlation_id=request.correlation_id,
                execution_id=record.execution_id,
                proposal_id=request.proposal_id,
                state=ActionExecutionState.UNKNOWN,
                connector_result="unknown",
                idempotency_key=request.idempotency_key,
                reconciliation_required=True,
                verification_required=True,
                audit_reference=self._audit_reference_for_unknown(request),
            )
        state = _state_for_result(response.result)
        if record is not None:
            record = _store_mark_remote_result(
                store,
                record,
                response,
                state,
                result_reference=self._audit_reference(request, response),
            )
            execution_id = record.execution_id
        else:
            execution_id = (
                "execution:"
                + hashlib.sha256(
                    f"{request.tenant_id}:{request.idempotency_key}:{request.request_checksum}".encode()
                ).hexdigest()
            )
        return ActionGatewayResponse(
            tenant_id=request.tenant_id,
            correlation_id=request.correlation_id,
            execution_id=execution_id,
            proposal_id=request.proposal_id,
            state=state,
            connector_result=response.result.value,
            remote_reference=response.remote_reference,
            idempotency_key=request.idempotency_key,
            reconciliation_required=response.reconciliation_required,
            verification_required=True,
            audit_reference=self._audit_reference(request, response),
        )

    execute = submit

    def _credentials(self, tenant_id: str, connector_id: str) -> Mapping[str, Any] | None:
        if self._secret_store is None:
            return None
        reader = getattr(self._secret_store, "read_action_connector_secret", None)
        if reader is None:
            raise ActionGatewayError("Action Gateway secret store is invalid")
        try:
            value = reader(tenant_id=tenant_id, connector_id=connector_id)
        except SecretAccessDenied as exc:
            raise ActionGatewayError("Action Gateway credentials are unavailable") from exc
        if not isinstance(value, Mapping):
            raise ActionGatewayError("Action Gateway credentials are malformed")
        return dict(value)

    def _audit_reference(
        self, request: ActionGatewayRequest, response: ActionConnectorResponse
    ) -> str:
        if self._audit_reference_factory is not None:
            return str(self._audit_reference_factory(request, response))
        return (
            "audit:action:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "tenant_id": request.tenant_id,
                        "case_id": request.case_id,
                        "proposal_id": request.proposal_id,
                        "idempotency_key": request.idempotency_key,
                        "result": response.result.value,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )

    def _audit_reference_for_unknown(self, request: ActionGatewayRequest) -> str:
        return (
            "audit:action-unknown:"
            + hashlib.sha256(
                f"{request.tenant_id}:{request.case_id}:{request.idempotency_key}:{request.request_checksum}".encode()
            ).hexdigest()
        )


def _state_for_result(result: ActionConnectorResult) -> ActionExecutionState:
    return {
        ActionConnectorResult.ACCEPTED: ActionExecutionState.PENDING_REMOTE,
        ActionConnectorResult.COMPLETED: ActionExecutionState.COMPLETED,
        ActionConnectorResult.REJECTED: ActionExecutionState.FAILED,
        ActionConnectorResult.FAILED: ActionExecutionState.FAILED,
        ActionConnectorResult.UNKNOWN: ActionExecutionState.UNKNOWN,
    }[result]


__all__ = ["ActionGateway", "ActionGatewayError"]


def _derive_request_identity(
    request: ActionGatewayRequest,
    authoritative_resource: object | Mapping[str, Any] | None,
) -> str:
    resource = _values(authoritative_resource)
    if not resource:
        raise ActionIdempotencyError("authoritative resource is required for canonical identity")
    return derive_action_idempotency_key(
        {
            "tenant_id": request.tenant_id,
            "case_id": request.case_id,
            "action_type": request.action_type.value,
            "parameters": dict(request.parameters),
            "requested_amount_minor": request.parameters.get("amount_minor"),
            "currency": request.parameters.get("currency"),
            "schema_version": "1.0.0",
        },
        connector_id=request.connector_id,
        authoritative_resource=resource,
    )


def _store_mark_validated(store: Any, record: ActionExecutionRecord) -> ActionExecutionRecord:
    ActionGatewayStateMachine.transition(record.status, ActionExecutionState.VALIDATED)
    updater = getattr(store, "update", None)
    if updater is not None:
        return updater(record, status=ActionExecutionState.VALIDATED)
    marker = getattr(store, "mark_validated", None)
    if marker is None:
        raise ActionGatewayError("execution store cannot persist validation")
    return marker(execution_id=record.execution_id)


def _store_mark_remote_result(
    store: Any,
    record: ActionExecutionRecord,
    response: ActionConnectorResponse,
    state: ActionExecutionState,
    result_reference: str | None = None,
) -> ActionExecutionRecord:
    if state is not ActionExecutionState.PENDING_REMOTE:
        record = _store_mark_pending_remote(store, record)
    updater = getattr(store, "update", None)
    if updater is not None:
        return updater(
            record,
            status=state,
            attempt_count=record.attempt_count + 1,
            reconciliation_state="required"
            if state is ActionExecutionState.UNKNOWN
            else "not_required",
            last_remote_result=response.result.value,
            remote_reference=response.remote_reference,
            result_reference=result_reference,
        )
    marker = getattr(store, "mark_remote_result", None)
    if marker is None:
        raise ActionGatewayError("execution store cannot persist connector result")
    return marker(
        execution_id=record.execution_id,
        result=response.result.value,
        remote_reference=response.remote_reference,
        result_reference=result_reference,
    )


def _response_from_record(record: ActionExecutionRecord) -> ActionGatewayResponse:
    return ActionGatewayResponse(
        tenant_id=record.tenant_id,
        correlation_id=record.correlation_id or record.case_id,
        execution_id=record.execution_id,
        proposal_id=record.proposal_id,
        state=record.status,
        connector_result=record.last_remote_result or record.status.value,
        remote_reference=record.remote_reference,
        idempotency_key=record.idempotency_key,
        reconciliation_required=record.status
        in {
            ActionExecutionState.UNKNOWN,
            ActionExecutionState.RECONCILING,
            ActionExecutionState.ESCALATED,
        },
        verification_required=record.status
        not in {
            ActionExecutionState.VERIFIED_SUCCESS,
            ActionExecutionState.VERIFIED_FAILURE,
            ActionExecutionState.ESCALATED,
        },
        audit_reference=record.result_reference or f"audit:execution:{record.execution_id}",
    )


def _store_mark_unknown(
    store: Any, record: ActionExecutionRecord, result_reference: str | None = None
) -> ActionExecutionRecord:
    if record.status is ActionExecutionState.VALIDATED:
        record = _store_mark_pending_remote(store, record)
    ActionGatewayStateMachine.transition(record.status, ActionExecutionState.UNKNOWN)
    updater = getattr(store, "update", None)
    if updater is not None:
        return updater(
            record,
            status=ActionExecutionState.UNKNOWN,
            attempt_count=record.attempt_count + 1,
            reconciliation_state="required",
            last_remote_result="unknown",
            result_reference=result_reference,
        )
    marker = getattr(store, "mark_remote_result", None)
    if marker is None:
        raise ActionGatewayError("execution store cannot persist unknown connector result")
    return marker(
        execution_id=record.execution_id,
        result="unknown",
        result_reference=result_reference,
    )


def _store_mark_pending_remote(store: Any, record: ActionExecutionRecord) -> ActionExecutionRecord:
    ActionGatewayStateMachine.transition(record.status, ActionExecutionState.PENDING_REMOTE)
    updater = getattr(store, "update", None)
    if updater is not None:
        return updater(record, status=ActionExecutionState.PENDING_REMOTE)
    marker = getattr(store, "mark_pending_remote", None)
    if marker is None:
        raise ActionGatewayError("execution store cannot persist remote submission")
    return marker(execution_id=record.execution_id)


def _values(value: object | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return dict(asdict(value))
    return dict(vars(value)) if hasattr(value, "__dict__") else {}
