"""Authoritative approval repository with database-enforced SoD checks."""

from __future__ import annotations

from datetime import datetime

from .base import TenantScopedRepository


class ApprovalRepository(TenantScopedRepository):
    def create(
        self,
        *,
        approval_id: str,
        correlation_id: str | None = None,
        case_id: str,
        proposal_id: str,
        approver_id: str,
        approver_role: str,
        proposer_id: str,
        scope: str,
        policy_version_id: str,
        status: str,
        approved_at: datetime,
        expires_at: datetime | None,
        separation_of_duties_evidence: str,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO approvals (
                tenant_id, approval_id, correlation_id, case_id, proposal_id, approver_id,
                approver_role, proposer_id, scope, policy_version_id, status,
                approved_at, expires_at, separation_of_duties_evidence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING tenant_id, approval_id, correlation_id, proposal_id, approver_id, status
            """,
            (
                self.tenant_context.tenant_id,
                approval_id,
                correlation_id or f"approval:{approval_id}",
                case_id,
                proposal_id,
                approver_id,
                approver_role,
                proposer_id,
                scope,
                policy_version_id,
                status,
                approved_at,
                expires_at,
                separation_of_duties_evidence,
            ),
        )
        if row is None:
            raise RuntimeError("approval insert returned no row")
        return row

    def get(self, *, approval_id: str) -> object | None:
        if not approval_id.strip():
            raise ValueError("approval_id is required")
        return self.fetch_one(
            """
            SELECT tenant_id, approval_id, case_id, proposal_id, approver_id,
                   approver_role, proposer_id, scope, policy_version_id, status,
                   approved_at, expires_at, separation_of_duties_evidence,
                   version, updated_at, correlation_id
            FROM public.approvals
            WHERE tenant_id = %s AND approval_id = %s
            """,
            (self.tenant_context.tenant_id, approval_id),
        )

    def update_status(
        self,
        *,
        approval_id: str,
        status: str,
        expected_version: int | None = None,
    ) -> object:
        if status not in {"approved", "rejected", "expired", "revoked"}:
            raise ValueError("approval status is invalid")
        where_version = "" if expected_version is None else " AND version = %s"
        parameters: tuple[object, ...] = (
            status,
            self.tenant_context.tenant_id,
            approval_id,
        )
        if expected_version is not None:
            parameters += (expected_version,)
        row = self.fetch_one(
            f"""
            UPDATE public.approvals
            SET status = %s, version = version + 1, updated_at = now()
            WHERE tenant_id = %s AND approval_id = %s{where_version}
            RETURNING tenant_id, approval_id, case_id, proposal_id, approver_id,
                      approver_role, proposer_id, scope, policy_version_id, status,
                      approved_at, expires_at, separation_of_duties_evidence,
                      version, updated_at, correlation_id
            """,
            parameters,
        )
        if row is None:
            raise ValueError("approval is missing or has a stale version")
        return row
