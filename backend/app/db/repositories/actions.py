"""Authoritative PostgreSQL repositories for canonical actions and executions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from action_gateway.idempotency import (
    ActionExecutionRecord,
    ActionIdempotencyError,
    execution_id_for,
    provider_idempotency_key_for,
    require_matching_canonical_identity,
)
from packages.contracts.action_gateway import ActionExecutionState, ActionGatewayRequest

from .base import RepositoryError, TenantScopedRepository
from .verifications import VerificationRepository


class CanonicalActionRepository(TenantScopedRepository):
    """Atomic persistence for an already validated semantic action identity."""

    def get_or_create(self, *, canonical_action_id: str, case_id: str) -> object:
        if not canonical_action_id.strip() or not case_id.strip():
            raise RepositoryError("canonical action and case identities are required")
        row = self.fetch_one(
            """
            INSERT INTO public.canonical_actions (
                tenant_id, canonical_action_id, case_id
            ) VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, canonical_action_id) DO NOTHING
            RETURNING tenant_id, canonical_action_id, case_id, identity_version, created_at
            """,
            (self.tenant_context.tenant_id, canonical_action_id, case_id),
        )
        if row is not None:
            return row
        row = self.fetch_one(
            """
            SELECT tenant_id, canonical_action_id, case_id, identity_version, created_at
            FROM public.canonical_actions
            WHERE tenant_id = %s AND canonical_action_id = %s
            """,
            (self.tenant_context.tenant_id, canonical_action_id),
        )
        if row is None or str(row[2]) != case_id:
            raise RepositoryError("canonical action identity conflicts with authoritative case")
        return row


class ActionExecutionRepository(TenantScopedRepository):
    """Persist one execution lifecycle per tenant/canonical action atomically."""

    def create(
        self,
        *,
        execution_id: str,
        case_id: str,
        proposal_id: str,
        policy_decision_id: str,
        approval_id: str | None = None,
        connector_id: str,
        idempotency_key: str,
        request_checksum: str,
        status: str,
        attempt_count: int = 0,
        canonical_action_id: str | None = None,
        resource_type: str | None = None,
        target_resource: str | None = None,
        provider_idempotency_key: str | None = None,
        reconciliation_state: str = "not_required",
        last_remote_result: str | None = None,
        remote_reference: str | None = None,
        result_reference: str | None = None,
        correlation_id: str | None = None,
    ) -> object:
        """Insert an execution row.

        The pre-T095 argument order is retained for existing repository callers.
        The T095 ``begin`` method is the production path and requires the
        canonical identity explicitly through the request key.
        """

        canonical = canonical_action_id or idempotency_key
        target = target_resource or "legacy"
        resource = resource_type or "legacy"
        provider_key = provider_idempotency_key or provider_idempotency_key_for(canonical)
        row = self.fetch_one(
            """
            INSERT INTO public.action_executions (
                tenant_id, execution_id, case_id, proposal_id, policy_decision_id, approval_id,
                connector_id, idempotency_key, request_checksum, status, attempt_count,
                canonical_action_id, resource_type, target_resource, provider_idempotency_key,
                reconciliation_state, last_remote_result, remote_reference, result_reference,
                correlation_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                      approval_id, connector_id, idempotency_key, request_checksum, status,
                      attempt_count, canonical_action_id, resource_type, target_resource,
                      provider_idempotency_key, reconciliation_state, last_remote_result,
                      remote_reference, result_reference, created_at, updated_at,
                      last_reconciled_at, correlation_id
            """,
            (
                self.tenant_context.tenant_id,
                execution_id,
                case_id,
                proposal_id,
                policy_decision_id,
                approval_id,
                connector_id,
                idempotency_key,
                request_checksum,
                status,
                attempt_count,
                canonical,
                resource,
                target,
                provider_key,
                reconciliation_state,
                last_remote_result,
                remote_reference,
                result_reference,
                correlation_id or f"case:{case_id}",
            ),
        )
        if row is None:
            raise RuntimeError("action execution insert returned no row")
        return row

    def begin(
        self,
        *,
        request: ActionGatewayRequest,
        canonical_action_id: str | None = None,
        resource_type: str,
        policy_decision_id: str,
        approval_id: str | None = None,
        provider_idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[ActionExecutionRecord, bool]:
        """Atomically claim or read the lifecycle for one canonical action."""

        self.assert_tenant(request.tenant_id)
        canonical = require_matching_canonical_identity(
            request, canonical_action_id=canonical_action_id or request.idempotency_key
        )
        if not resource_type.strip() or not policy_decision_id.strip():
            raise ActionIdempotencyError("resource type and policy decision are required")
        provider_key = provider_idempotency_key or provider_idempotency_key_for(canonical)
        execution_id = execution_id_for(tenant_id=request.tenant_id, canonical_action_id=canonical)
        self.fetch_one(
            """
            INSERT INTO public.canonical_actions (tenant_id, canonical_action_id, case_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, canonical_action_id) DO NOTHING
            RETURNING canonical_action_id
            """,
            (request.tenant_id, canonical, request.case_id),
        )
        inserted = self.fetch_one(
            """
            INSERT INTO public.action_executions (
                tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                approval_id, connector_id, idempotency_key, request_checksum, status,
                attempt_count, canonical_action_id, resource_type, target_resource,
                provider_idempotency_key, reconciliation_state, correlation_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, 'received', 0,
                %s, %s, %s, %s, 'not_required', %s
            )
            ON CONFLICT (tenant_id, canonical_action_id) DO NOTHING
            RETURNING tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                      approval_id, connector_id, idempotency_key, request_checksum, status,
                      attempt_count, canonical_action_id, resource_type, target_resource,
                      provider_idempotency_key, reconciliation_state, last_remote_result,
                      remote_reference, result_reference, created_at, updated_at,
                      last_reconciled_at, correlation_id
            """,
            (
                request.tenant_id,
                execution_id,
                request.case_id,
                request.proposal_id,
                policy_decision_id,
                approval_id,
                request.connector_id,
                request.idempotency_key,
                request.request_checksum,
                canonical,
                resource_type,
                request.target_resource,
                provider_key,
                correlation_id or request.correlation_id,
            ),
        )
        if inserted is not None:
            return _record_from_row(inserted), True
        existing = self._get_by_canonical(canonical_action_id=canonical)
        if existing is None:
            raise RepositoryError("execution disappeared after canonical identity conflict")
        _assert_existing_request(
            existing,
            request,
            canonical,
            resource_type,
            policy_decision_id,
            approval_id=approval_id,
        )
        return _record_from_row(existing), False

    def get_by_idempotency_key(self, *, idempotency_key: str) -> object | None:
        return self.fetch_one(
            """
            SELECT tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                   approval_id, connector_id, idempotency_key, request_checksum, status,
                   attempt_count, canonical_action_id, resource_type, target_resource,
                   provider_idempotency_key, reconciliation_state, last_remote_result,
                   remote_reference, result_reference, created_at, updated_at,
                   last_reconciled_at, correlation_id
            FROM public.action_executions
            WHERE tenant_id = %s AND idempotency_key = %s
            """,
            (self.tenant_context.tenant_id, idempotency_key),
        )

    def get(self, *, execution_id: str) -> ActionExecutionRecord | None:
        row = self.fetch_one(
            """
            SELECT tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                   approval_id, connector_id, idempotency_key, request_checksum, status,
                   attempt_count, canonical_action_id, resource_type, target_resource,
                   provider_idempotency_key, reconciliation_state, last_remote_result,
                   remote_reference, result_reference, created_at, updated_at,
                   last_reconciled_at, correlation_id
             FROM public.action_executions
             WHERE tenant_id = %s AND execution_id = %s
            """,
            (self.tenant_context.tenant_id, execution_id),
        )
        return None if row is None else _record_from_row(row)

    def get_by_canonical(self, *, canonical_action_id: str) -> ActionExecutionRecord | None:
        row = self._get_by_canonical(canonical_action_id=canonical_action_id)
        return None if row is None else _record_from_row(row)

    def mark_remote_result(
        self,
        *,
        execution_id: str,
        result: str,
        remote_reference: str | None = None,
        result_reference: str | None = None,
    ) -> ActionExecutionRecord:
        result = result.strip().lower()
        status = {
            "accepted": ActionExecutionState.PENDING_REMOTE.value,
            "submitted": ActionExecutionState.PENDING_REMOTE.value,
            "completed": ActionExecutionState.COMPLETED.value,
            "succeeded": ActionExecutionState.COMPLETED.value,
            "rejected": ActionExecutionState.FAILED.value,
            "failed": ActionExecutionState.FAILED.value,
            "unknown": ActionExecutionState.UNKNOWN.value,
        }.get(result)
        if status is None:
            raise RepositoryError("unsupported remote action result")
        reconciliation = (
            "required" if status == ActionExecutionState.UNKNOWN.value else "not_required"
        )
        row = self.fetch_one(
            """
            UPDATE public.action_executions
            SET status = %s, last_remote_result = %s,
                remote_reference = COALESCE(%s, remote_reference),
                result_reference = COALESCE(%s, result_reference),
                reconciliation_state = %s, attempt_count = attempt_count + 1, updated_at = now()
             WHERE tenant_id = %s AND execution_id = %s
               AND status IN ('validated', 'pending_remote')
            RETURNING tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                      approval_id, connector_id, idempotency_key, request_checksum, status,
                      attempt_count, canonical_action_id, resource_type, target_resource,
                      provider_idempotency_key, reconciliation_state, last_remote_result,
                      remote_reference, result_reference, created_at, updated_at,
                      last_reconciled_at, correlation_id
            """,
            (
                status,
                result,
                remote_reference,
                result_reference,
                reconciliation,
                self.tenant_context.tenant_id,
                execution_id,
            ),
        )
        if row is None:
            raise RepositoryError("action execution does not exist for this tenant")
        return _record_from_row(row)

    def mark_validated(self, *, execution_id: str) -> ActionExecutionRecord:
        """Record the validation boundary before any connector call."""

        self.execute(
            """
            UPDATE public.action_executions
            SET status = 'validated', updated_at = now()
            WHERE tenant_id = %s AND execution_id = %s AND status = 'received'
            """,
            (self.tenant_context.tenant_id, execution_id),
        )
        record = self.get(execution_id=execution_id)
        if record is None or record.status is not ActionExecutionState.VALIDATED:
            raise RepositoryError("execution is not eligible for validation")
        return record

    def mark_pending_remote(self, *, execution_id: str) -> ActionExecutionRecord:
        """Record that the isolated gateway handed the request to a connector."""

        self.execute(
            """
            UPDATE public.action_executions
            SET status = 'pending_remote', updated_at = now()
            WHERE tenant_id = %s AND execution_id = %s AND status = 'validated'
            """,
            (self.tenant_context.tenant_id, execution_id),
        )
        record = self.get(execution_id=execution_id)
        if record is None or record.status is not ActionExecutionState.PENDING_REMOTE:
            raise RepositoryError("execution is not eligible for remote submission")
        return record

    def mark_unknown(self, *, execution_id: str) -> ActionExecutionRecord:
        """Fail closed when recovery finds a request without a durable remote result."""

        self.execute(
            """
            UPDATE public.action_executions
            SET status = 'unknown', reconciliation_state = 'required',
                last_remote_result = 'unknown', updated_at = now()
            WHERE tenant_id = %s AND execution_id = %s
              AND status IN ('received', 'validated', 'pending_remote')
            """,
            (self.tenant_context.tenant_id, execution_id),
        )
        record = self.get(execution_id=execution_id)
        if record is None or record.status is not ActionExecutionState.UNKNOWN:
            raise RepositoryError("execution is not eligible for uncertain recovery")
        return record

    def mark_reconciling(self, *, execution_id: str) -> ActionExecutionRecord:
        row = self.fetch_one(
            """
            UPDATE public.action_executions
            SET status = 'reconciling', reconciliation_state = 'in_progress', updated_at = now()
            WHERE tenant_id = %s AND execution_id = %s AND status = 'unknown'
            RETURNING tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                      approval_id, connector_id, idempotency_key, request_checksum, status,
                      attempt_count, canonical_action_id, resource_type, target_resource,
                      provider_idempotency_key, reconciliation_state, last_remote_result,
                      remote_reference, result_reference, created_at, updated_at,
                      last_reconciled_at, correlation_id
            """,
            (self.tenant_context.tenant_id, execution_id),
        )
        if row is None:
            raise RepositoryError("only an UNKNOWN execution can enter reconciliation")
        return _record_from_row(row)

    def mark_reconciled(
        self,
        *,
        execution_id: str,
        remote_state: str,
        effect_occurred: bool | None,
    ) -> ActionExecutionRecord:
        if effect_occurred is True:
            status = ActionExecutionState.VERIFIED_SUCCESS.value
            reconciliation = "resolved"
        elif effect_occurred is False:
            status = ActionExecutionState.RECONCILED.value
            reconciliation = "resolved"
        else:
            status = ActionExecutionState.ESCALATED.value
            reconciliation = "unresolved"
        row = self.fetch_one(
            """
            UPDATE public.action_executions
            SET status = %s, reconciliation_state = %s, last_remote_result = %s,
                last_reconciled_at = now(), updated_at = now()
            WHERE tenant_id = %s AND execution_id = %s AND status = 'reconciling'
            RETURNING tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                      approval_id, connector_id, idempotency_key, request_checksum, status,
                      attempt_count, canonical_action_id, resource_type, target_resource,
                      provider_idempotency_key, reconciliation_state, last_remote_result,
                      remote_reference, result_reference, created_at, updated_at,
                      last_reconciled_at, correlation_id
            """,
            (
                status,
                reconciliation,
                remote_state,
                self.tenant_context.tenant_id,
                execution_id,
            ),
        )
        if row is None:
            raise RepositoryError("execution is not awaiting reconciliation")
        return _record_from_row(row)

    def mark_verified(
        self, *, execution_id: str, success: bool, result_reference: str
    ) -> ActionExecutionRecord:
        if not result_reference.strip():
            raise RepositoryError("verification result reference is required")
        row = self.fetch_one(
            """
            UPDATE public.action_executions
            SET status = %s, result_reference = %s, updated_at = now()
            WHERE tenant_id = %s AND execution_id = %s
              AND status IN ('completed', 'reconciled', 'verifying')
            RETURNING tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                      approval_id, connector_id, idempotency_key, request_checksum, status,
                      attempt_count, canonical_action_id, resource_type, target_resource,
                      provider_idempotency_key, reconciliation_state, last_remote_result,
                      remote_reference, result_reference, created_at, updated_at,
                      last_reconciled_at, correlation_id
            """,
            (
                ActionExecutionState.VERIFIED_SUCCESS.value
                if success
                else ActionExecutionState.VERIFIED_FAILURE.value,
                result_reference,
                self.tenant_context.tenant_id,
                execution_id,
            ),
        )
        if row is None:
            raise RepositoryError("execution is not eligible for verification")
        return _record_from_row(row)

    def mark_escalated(self, *, execution_id: str, result_reference: str) -> ActionExecutionRecord:
        if not result_reference.strip():
            raise RepositoryError("escalation reference is required")
        row = self.fetch_one(
            """
            UPDATE public.action_executions
             SET status = 'escalated', result_reference = %s, reconciliation_state =
                 CASE WHEN status = 'unknown' THEN 'unresolved' ELSE reconciliation_state END,
                 updated_at = now()
             WHERE tenant_id = %s AND execution_id = %s
               AND status IN (
                   'completed', 'failed', 'reconciled', 'verifying', 'unknown',
                   'reconciling', 'escalated'
               )
            RETURNING tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                      approval_id, connector_id, idempotency_key, request_checksum, status,
                      attempt_count, canonical_action_id, resource_type, target_resource,
                      provider_idempotency_key, reconciliation_state, last_remote_result,
                      remote_reference, result_reference, created_at, updated_at,
                      last_reconciled_at, correlation_id
            """,
             (result_reference, self.tenant_context.tenant_id, execution_id),
        )
        if row is None:
            raise RepositoryError("action execution does not exist for this tenant")
        return _record_from_row(row)

    def _get_by_canonical(self, *, canonical_action_id: str) -> object | None:
        return self.fetch_one(
            """
            SELECT tenant_id, execution_id, case_id, proposal_id, policy_decision_id,
                   approval_id, connector_id, idempotency_key, request_checksum, status,
                   attempt_count, canonical_action_id, resource_type, target_resource,
                   provider_idempotency_key, reconciliation_state, last_remote_result,
                   remote_reference, result_reference, created_at, updated_at,
                   last_reconciled_at, correlation_id
            FROM public.action_executions
            WHERE tenant_id = %s AND canonical_action_id = %s
            """,
            (self.tenant_context.tenant_id, canonical_action_id),
        )


def _assert_existing_request(
    existing: object,
    request: ActionGatewayRequest,
    canonical_action_id: str,
    resource_type: str,
    policy_decision_id: str,
    *,
    approval_id: str | None = None,
) -> None:
    values = _row_values(existing)
    expected = {
        "tenant_id": request.tenant_id,
        "case_id": request.case_id,
        "connector_id": request.connector_id,
        "idempotency_key": request.idempotency_key,
        "request_checksum": request.request_checksum,
        "canonical_action_id": canonical_action_id,
        "resource_type": resource_type,
        "target_resource": request.target_resource,
        "policy_decision_id": policy_decision_id,
    }
    if approval_id is not None:
        expected["approval_id"] = approval_id
    for key, expected_value in expected.items():
        if values.get(key) is not None and str(values[key]) != str(expected_value):
            raise ActionIdempotencyError(f"existing execution {key} does not match request")


def _record_from_row(row: Any) -> ActionExecutionRecord:
    values = _row_values(row)
    canonical = str(values.get("canonical_action_id") or values["idempotency_key"])
    return ActionExecutionRecord(
        tenant_id=str(values["tenant_id"]),
        execution_id=str(values["execution_id"]),
        case_id=str(values["case_id"]),
        proposal_id=str(values["proposal_id"]),
        policy_decision_id=str(values["policy_decision_id"]),
        approval_id=None if values.get("approval_id") is None else str(values["approval_id"]),
        connector_id=str(values["connector_id"]),
        idempotency_key=str(values["idempotency_key"]),
        request_checksum=str(values["request_checksum"]),
        canonical_action_id=canonical,
        resource_type=str(values.get("resource_type") or "legacy"),
        target_resource=str(values.get("target_resource") or "legacy"),
        provider_idempotency_key=str(
            values.get("provider_idempotency_key") or provider_idempotency_key_for(canonical)
        ),
        status=ActionExecutionState(str(values["status"])),
        attempt_count=int(values.get("attempt_count", 0)),
        reconciliation_state=str(values.get("reconciliation_state") or "not_required"),
        last_remote_result=(
            None if values.get("last_remote_result") is None else str(values["last_remote_result"])
        ),
        remote_reference=(
            None if values.get("remote_reference") is None else str(values["remote_reference"])
        ),
        result_reference=(
            None if values.get("result_reference") is None else str(values["result_reference"])
        ),
        created_at=values.get("created_at"),
        updated_at=values.get("updated_at"),
        last_reconciled_at=values.get("last_reconciled_at"),
        correlation_id=(
            None if values.get("correlation_id") is None else str(values["correlation_id"])
        ),
    )


def _row_values(row: object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    names = (
        "tenant_id",
        "execution_id",
        "case_id",
        "proposal_id",
        "policy_decision_id",
        "approval_id",
        "connector_id",
        "idempotency_key",
        "request_checksum",
        "status",
        "attempt_count",
        "canonical_action_id",
        "resource_type",
        "target_resource",
        "provider_idempotency_key",
        "reconciliation_state",
        "last_remote_result",
        "remote_reference",
        "result_reference",
        "created_at",
        "updated_at",
        "last_reconciled_at",
        "correlation_id",
    )
    return {name: row[index] for index, name in enumerate(names) if index < len(row)}  # type: ignore[arg-type]


__all__ = ["ActionExecutionRepository", "CanonicalActionRepository", "VerificationRepository"]
