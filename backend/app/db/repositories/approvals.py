"""Authoritative approval repository with database-enforced SoD checks."""

from __future__ import annotations

from datetime import datetime

from .base import TenantScopedRepository


class ApprovalRepository(TenantScopedRepository):
    def create(
        self,
        *,
        approval_id: str,
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
                tenant_id, approval_id, case_id, proposal_id, approver_id,
                approver_role, proposer_id, scope, policy_version_id, status,
                approved_at, expires_at, separation_of_duties_evidence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING tenant_id, approval_id, proposal_id, approver_id, status
            """,
            (
                self.tenant_context.tenant_id,
                approval_id,
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
