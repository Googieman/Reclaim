"""Authoritative repositories for immutable policy versions and decisions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json

from .base import TenantScopedRepository


class PolicyVersionRepository(TenantScopedRepository):
    def create(
        self,
        *,
        policy_version_id: str,
        scope_type: str,
        thresholds: Mapping[str, object],
        action_allowlist: list[str],
        approval_rules: Mapping[str, object],
        effective_from: datetime,
        effective_to: datetime | None,
        author: str,
        publication_status: str,
        immutable_checksum: str,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO policy_versions (
                policy_version_id, tenant_id, scope_type, thresholds, action_allowlist,
                approval_rules, effective_from, effective_to, author,
                publication_status, immutable_checksum
            )
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
            RETURNING policy_version_id, tenant_id, scope_type, publication_status,
                      immutable_checksum
            """,
            (
                policy_version_id,
                self.tenant_context.tenant_id,
                scope_type,
                json.dumps(thresholds, sort_keys=True, separators=(",", ":")),
                json.dumps(action_allowlist, separators=(",", ":")),
                json.dumps(approval_rules, sort_keys=True, separators=(",", ":")),
                effective_from,
                effective_to,
                author,
                publication_status,
                immutable_checksum,
            ),
        )
        if row is None:
            raise RuntimeError("policy version insert returned no row")
        return row


class PolicyDecisionRepository(TenantScopedRepository):
    def create(
        self,
        *,
        decision_id: str,
        case_id: str,
        proposal_id: str,
        policy_version_id: str,
        result: str,
        evaluated_conditions: Mapping[str, object],
        evaluator_version: str,
        decided_at: datetime,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO policy_decisions (
                tenant_id, decision_id, case_id, proposal_id, policy_version_id,
                result, evaluated_conditions, evaluator_version, decided_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING tenant_id, decision_id, proposal_id, policy_version_id, result,
                      decided_at
            """,
            (
                self.tenant_context.tenant_id,
                decision_id,
                case_id,
                proposal_id,
                policy_version_id,
                result,
                json.dumps(evaluated_conditions, sort_keys=True, separators=(",", ":")),
                evaluator_version,
                decided_at,
            ),
        )
        if row is None:
            raise RuntimeError("policy decision insert returned no row")
        return row
