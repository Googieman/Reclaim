"""Authoritative Action Gateway execution and verification repositories."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from .base import TenantScopedRepository


class ActionExecutionRepository(TenantScopedRepository):
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
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO action_executions (
                tenant_id, execution_id, case_id, proposal_id, policy_decision_id, approval_id,
                connector_id, idempotency_key, request_checksum, status, attempt_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING tenant_id, execution_id, proposal_id, idempotency_key, status,
                      attempt_count, approval_id
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
            ),
        )
        if row is None:
            raise RuntimeError("action execution insert returned no row")
        return row

    def get_by_idempotency_key(self, *, idempotency_key: str) -> object | None:
        return self.fetch_one(
            """
            SELECT tenant_id, execution_id, proposal_id, status, remote_reference,
                   attempt_count, result_reference
            FROM action_executions
            WHERE tenant_id = %s AND idempotency_key = %s
            """,
            (self.tenant_context.tenant_id, idempotency_key),
        )


class VerificationRepository(TenantScopedRepository):
    def create(
        self,
        *,
        verification_id: str,
        execution_id: str,
        case_id: str,
        observed_resource_state: str,
        verifier_source: str,
        result: str,
        evidence_references: Sequence[str],
        verified_at: datetime,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO verifications (
                tenant_id, verification_id, execution_id, case_id,
                observed_resource_state, verifier_source, result,
                evidence_references, verified_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING tenant_id, verification_id, execution_id, result, verified_at
            """,
            (
                self.tenant_context.tenant_id,
                verification_id,
                execution_id,
                case_id,
                observed_resource_state,
                verifier_source,
                result,
                json.dumps(list(evidence_references), separators=(",", ":")),
                verified_at,
            ),
        )
        if row is None:
            raise RuntimeError("verification insert returned no row")
        return row
