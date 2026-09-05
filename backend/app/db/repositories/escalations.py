"""Authoritative unresolved-case escalation repository."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from .base import RepositoryError, TenantScopedRepository


class EscalationRepository(TenantScopedRepository):
    def create(
        self,
        *,
        escalation_id: str,
        case_id: str,
        owner: str,
        reason: str,
        remaining_exposure_minor: int,
        evidence_references: Sequence[str],
        recommended_human_decision: str,
        owner_tenant_id: str | None = None,
        currency: str = "INR",
        canonical_action_id: str | None = None,
        execution_id: str | None = None,
        verification_id: str | None = None,
        policy_version_id: str | None = None,
        action_version: str = "action-idempotency-v1.0.0",
        verification_version: str | None = None,
        checksum: str | None = None,
        state: str = "open",
        created_at: datetime | None = None,
        correlation_id: str | None = None,
    ) -> object:
        if state not in {"open", "resolved"}:
            raise RepositoryError("escalation state is unsupported")
        row = self.fetch_one(
            """
            INSERT INTO public.escalations (
                tenant_id, escalation_id, case_id, owner, owner_tenant_id,
                reason, remaining_exposure_minor, currency, evidence_references,
                recommended_human_decision, canonical_action_id, execution_id,
                verification_id, policy_version_id, action_version,
                verification_version, checksum, state, created_at
                , correlation_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, COALESCE(%s, now()), %s)
            RETURNING tenant_id, escalation_id, case_id, owner, owner_tenant_id,
                      reason, remaining_exposure_minor, currency, evidence_references,
                      recommended_human_decision, canonical_action_id, execution_id,
                      verification_id, policy_version_id, action_version,
                      verification_version, checksum, state, created_at, resolved_at
                      , correlation_id
            """,
            (
                self.tenant_context.tenant_id,
                escalation_id,
                case_id,
                owner,
                owner_tenant_id or self.tenant_context.tenant_id,
                reason,
                remaining_exposure_minor,
                currency,
                json.dumps(list(evidence_references), separators=(",", ":")),
                recommended_human_decision,
                canonical_action_id,
                execution_id,
                verification_id,
                policy_version_id,
                action_version,
                verification_version,
                checksum,
                state,
                created_at,
                correlation_id,
            ),
        )
        if row is None:
            raise RuntimeError("escalation insert returned no row")
        return row

    def get(self, *, escalation_id: str) -> object | None:
        return self.fetch_one(
            """
            SELECT tenant_id, escalation_id, case_id, owner, owner_tenant_id,
                   reason, remaining_exposure_minor, currency, evidence_references,
                   recommended_human_decision, canonical_action_id, execution_id,
                   verification_id, policy_version_id, action_version,
                   verification_version, checksum, state, created_at, resolved_at,
                   correlation_id
            FROM public.escalations
            WHERE tenant_id = %s AND escalation_id = %s
            """,
            (self.tenant_context.tenant_id, escalation_id),
        )

    def for_case(self, *, case_id: str) -> list[object]:
        return self.fetch_all(
            """
            SELECT tenant_id, escalation_id, case_id, owner, owner_tenant_id,
                   reason, remaining_exposure_minor, currency, evidence_references,
                   recommended_human_decision, canonical_action_id, execution_id,
                   verification_id, policy_version_id, action_version,
                   verification_version, checksum, state, created_at, resolved_at,
                   correlation_id
            FROM public.escalations
            WHERE tenant_id = %s AND case_id = %s
            ORDER BY created_at, escalation_id
            """,
            (self.tenant_context.tenant_id, case_id),
        )

    def resolve(
        self, *, escalation_id: str, expected_version: int, resolved_at: datetime | None = None
    ) -> object:
        row = self.fetch_one(
            """
            UPDATE public.escalations
            SET state = 'resolved', version = version + 1,
                resolved_at = COALESCE(%s, now()), updated_at = now()
            WHERE tenant_id = %s AND escalation_id = %s AND state = 'open'
              AND version = %s
            RETURNING tenant_id, escalation_id, case_id, owner, owner_tenant_id,
                      reason, remaining_exposure_minor, currency, evidence_references,
                      recommended_human_decision, canonical_action_id, execution_id,
                      verification_id, policy_version_id, action_version,
                      verification_version, checksum, state, created_at, resolved_at,
                      correlation_id
            """,
            (resolved_at, self.tenant_context.tenant_id, escalation_id, expected_version),
        )
        if row is None:
            raise RepositoryError("escalation is missing, resolved, or stale")
        return row


__all__ = ["EscalationRepository"]
