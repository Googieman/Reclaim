"""UNKNOWN-result reconciliation and retry safety for the Action Gateway."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from packages.contracts.action_gateway import ActionExecutionState, ActionGatewayRequest

from .idempotency import (
    ActionExecutionRecord,
    ActionIdempotencyError,
    ExecutionStore,
    InMemoryActionExecutionStore,
)


class RemoteAction(Protocol):
    def invoke(self, idempotency_key: str) -> Any: ...

    def reconcile(self, idempotency_key: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Authoritative recovery result and evidence of the retry decision."""

    state: ActionExecutionState
    execution_id: str
    idempotency_key: str
    reconciliation_performed: bool
    retry_before_reconciliation: bool
    retry_performed: bool
    effect_occurred: bool | None
    remote_state: str
    attempt_count: int
    record: ActionExecutionRecord | None = None


class ReconciliationRequiredError(ActionIdempotencyError):
    """Raised when a caller attempts a new provider request from UNKNOWN."""


def reconcile_unknown(
    *,
    record: ActionExecutionRecord,
    remote: RemoteAction,
    store: ExecutionStore,
) -> RecoveryResult:
    """Reconcile UNKNOWN exactly once before considering another provider request."""

    if record.status is not ActionExecutionState.UNKNOWN:
        raise ReconciliationRequiredError("reconciliation requires an UNKNOWN execution")
    in_progress = _update_reconciling(store, record)
    remote_value = _remote_value(remote.reconcile(record.provider_idempotency_key))
    reconciled_at = datetime.now(UTC)
    if remote_value in {"completed", "succeeded", "accepted", "submitted"}:
        resolved = _update_reconciled(
            store,
            in_progress,
            remote_state=remote_value,
            effect_occurred=True,
            reconciled_at=reconciled_at,
        )
        return RecoveryResult(
            state=ActionExecutionState.VERIFIED_SUCCESS,
            execution_id=resolved.execution_id,
            idempotency_key=resolved.idempotency_key,
            reconciliation_performed=True,
            retry_before_reconciliation=False,
            retry_performed=False,
            effect_occurred=True,
            remote_state=remote_value,
            attempt_count=resolved.attempt_count,
            record=resolved,
        )
    if remote_value in {"not_found", "not_submitted", "absent", "failed"}:
        resolved = _update_reconciled(
            store,
            in_progress,
            remote_state=remote_value,
            effect_occurred=False,
            reconciled_at=reconciled_at,
        )
        return RecoveryResult(
            state=ActionExecutionState.RECONCILED,
            execution_id=resolved.execution_id,
            idempotency_key=resolved.idempotency_key,
            reconciliation_performed=True,
            retry_before_reconciliation=False,
            retry_performed=False,
            effect_occurred=False,
            remote_state=remote_value,
            attempt_count=resolved.attempt_count,
            record=resolved,
        )
    unresolved = _update_reconciled(
        store,
        in_progress,
        remote_state=remote_value,
        effect_occurred=None,
        reconciled_at=reconciled_at,
    )
    return RecoveryResult(
        state=ActionExecutionState.ESCALATED,
        execution_id=unresolved.execution_id,
        idempotency_key=unresolved.idempotency_key,
        reconciliation_performed=True,
        retry_before_reconciliation=False,
        retry_performed=False,
        effect_occurred=None,
        remote_state=remote_value,
        attempt_count=unresolved.attempt_count,
        record=unresolved,
    )


def _update_reconciling(
    store: ExecutionStore, record: ActionExecutionRecord
) -> ActionExecutionRecord:
    updater = getattr(store, "update", None)
    if updater is not None:
        return updater(
            record,
            status=ActionExecutionState.RECONCILING,
            reconciliation_state="in_progress",
        )
    marker = getattr(store, "mark_reconciling", None)
    if marker is None:
        raise ReconciliationRequiredError("execution store cannot persist reconciliation")
    return marker(execution_id=record.execution_id)


def _update_reconciled(
    store: ExecutionStore,
    record: ActionExecutionRecord,
    *,
    remote_state: str,
    effect_occurred: bool | None,
    reconciled_at: datetime,
) -> ActionExecutionRecord:
    updater = getattr(store, "update", None)
    if updater is not None:
        status = (
            ActionExecutionState.VERIFIED_SUCCESS
            if effect_occurred is True
            else ActionExecutionState.RECONCILED
            if effect_occurred is False
            else ActionExecutionState.ESCALATED
        )
        return updater(
            record,
            status=status,
            reconciliation_state="resolved" if effect_occurred is not None else "unresolved",
            last_remote_result=remote_state,
            last_reconciled_at=reconciled_at,
        )
    marker = getattr(store, "mark_reconciled", None)
    if marker is None:
        raise ReconciliationRequiredError("execution store cannot persist reconciliation result")
    return marker(
        execution_id=record.execution_id,
        remote_state=remote_state,
        effect_occurred=effect_occurred,
    )


def recover_action(
    *,
    request: ActionGatewayRequest,
    remote: RemoteAction,
    process_restart: bool = False,
    timeout: bool = False,
    duplicate_deliveries: int = 0,
    late_remote_response: bool = False,
    store: ExecutionStore | None = None,
    canonical_action_id: str | None = None,
    resource_type: str | None = None,
    policy_decision_id: str | None = None,
    approval_id: str | None = None,
) -> RecoveryResult:
    """Recover one action from a durable store and reconcile ambiguous results.

    ``process_restart``, duplicate delivery, and a late response are recovery
    conditions, not permission to make an extra provider call.  The production
    repository implementation supplies the atomic insert/update operations;
    this default store exists only for deterministic local tests.
    """

    del process_restart, duplicate_deliveries, late_remote_response
    execution_store = store or InMemoryActionExecutionStore()
    existing = _existing_record(execution_store, request)
    resource = resource_type or _record_text(existing, "resource_type") or "unknown"
    policy_id = (
        policy_decision_id or _record_text(existing, "policy_decision_id") or "recovery-policy"
    )
    approval = approval_id if approval_id is not None else _record_text(existing, "approval_id")
    record, inserted = execution_store.begin(
        request=request,
        canonical_action_id=canonical_action_id,
        resource_type=resource,
        policy_decision_id=policy_id,
        approval_id=approval,
    )
    if not inserted:
        if record.status is ActionExecutionState.UNKNOWN:
            return reconcile_unknown(record=record, remote=remote, store=execution_store)
        if record.status in {
            ActionExecutionState.RECEIVED,
            ActionExecutionState.VALIDATED,
            ActionExecutionState.PENDING_REMOTE,
        }:
            uncertain = _mark_uncertain(execution_store, record)
            return reconcile_unknown(record=uncertain, remote=remote, store=execution_store)
        return RecoveryResult(
            state=record.status,
            execution_id=record.execution_id,
            idempotency_key=record.idempotency_key,
            reconciliation_performed=record.reconciliation_state
            in {"in_progress", "resolved", "unresolved"},
            retry_before_reconciliation=False,
            retry_performed=False,
            effect_occurred=record.status
            in {ActionExecutionState.COMPLETED, ActionExecutionState.VERIFIED_SUCCESS},
            remote_state=record.last_remote_result or record.status.value,
            attempt_count=record.attempt_count,
            record=record,
        )

    response = _remote_value(remote.invoke(record.provider_idempotency_key))
    attempted = execution_store.update(
        record,
        attempt_count=record.attempt_count + 1,
        status=(
            ActionExecutionState.UNKNOWN
            if timeout and response in {"accepted", "submitted"}
            else _state_for_remote(response)
        ),
        reconciliation_state=(
            "required"
            if response == "unknown" or (timeout and response in {"accepted", "submitted"})
            else "not_required"
        ),
        last_remote_result=response,
    )
    # A completed or failed response is already a known remote outcome.  A
    # timeout only converts an ambiguous/pending response into reconciliation;
    # it must never cause a second provider request.
    if response == "unknown" or (timeout and response in {"accepted", "submitted"}):
        return reconcile_unknown(record=attempted, remote=remote, store=execution_store)
    return RecoveryResult(
        state=attempted.status,
        execution_id=attempted.execution_id,
        idempotency_key=attempted.idempotency_key,
        reconciliation_performed=False,
        retry_before_reconciliation=False,
        retry_performed=False,
        effect_occurred=response in {"completed", "succeeded"},
        remote_state=response,
        attempt_count=attempted.attempt_count,
        record=attempted,
    )


def _state_for_remote(value: str) -> ActionExecutionState:
    return {
        "accepted": ActionExecutionState.PENDING_REMOTE,
        "submitted": ActionExecutionState.PENDING_REMOTE,
        "completed": ActionExecutionState.COMPLETED,
        "succeeded": ActionExecutionState.COMPLETED,
        "failed": ActionExecutionState.FAILED,
        "rejected": ActionExecutionState.FAILED,
        "unknown": ActionExecutionState.UNKNOWN,
    }.get(value, ActionExecutionState.UNKNOWN)


def _mark_uncertain(store: ExecutionStore, record: ActionExecutionRecord) -> ActionExecutionRecord:
    updater = getattr(store, "update", None)
    if updater is not None:
        return updater(
            record,
            status=ActionExecutionState.UNKNOWN,
            reconciliation_state="required",
            last_remote_result="unknown",
        )
    marker = getattr(store, "mark_unknown", None)
    if marker is None:
        raise ReconciliationRequiredError(
            "execution store cannot persist an uncertain restart state"
        )
    return marker(execution_id=record.execution_id)


def _existing_record(
    store: ExecutionStore, request: ActionGatewayRequest
) -> ActionExecutionRecord | None:
    for getter_name in ("get", "get_by_canonical"):
        getter = getattr(store, getter_name, None)
        if getter is None:
            continue
        try:
            record = getter(
                tenant_id=request.tenant_id,
                canonical_action_id=request.idempotency_key,
            )
        except TypeError:
            try:
                record = getter(canonical_action_id=request.idempotency_key)
            except TypeError:
                continue
        if isinstance(record, ActionExecutionRecord):
            return record
    return None


def _record_text(record: ActionExecutionRecord | None, field: str) -> str | None:
    value = getattr(record, field, None)
    return value if isinstance(value, str) and value.strip() else None


def _remote_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    result = getattr(value, "value", None)
    if isinstance(result, str):
        return result.strip().lower()
    if isinstance(value, dict):
        for key in ("state", "result", "status"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate.strip().lower()
    return "unknown"


__all__ = [
    "RecoveryResult",
    "ReconciliationRequiredError",
    "RemoteAction",
    "reconcile_unknown",
    "recover_action",
]
