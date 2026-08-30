"""Authoritative typed action-proposal repository."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json

from .base import TenantScopedRepository


class ActionProposalRepository(TenantScopedRepository):
    def create(
        self,
        *,
        proposal_id: str,
        case_id: str,
        action_type: str,
        target_resource: str,
        parameters: Mapping[str, object],
        rationale: str,
        evidence_references: Sequence[str],
        attribution_references: Sequence[str],
        requested_amount_minor: int | None,
        currency: str | None,
        idempotency_key: str,
        analysis_id: str,
        status: str = "created",
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO action_proposals (
                tenant_id, proposal_id, case_id, action_type, target_resource, parameters,
                rationale, evidence_references, attribution_references,
                requested_amount_minor, currency, idempotency_key, analysis_id, status
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, %s)
            RETURNING tenant_id, proposal_id, case_id, action_type, idempotency_key, status
            """,
            (
                self.tenant_context.tenant_id,
                proposal_id,
                case_id,
                action_type,
                target_resource,
                json.dumps(parameters, sort_keys=True, separators=(",", ":")),
                rationale,
                json.dumps(list(evidence_references), separators=(",", ":")),
                json.dumps(list(attribution_references), separators=(",", ":")),
                requested_amount_minor,
                currency,
                idempotency_key,
                analysis_id,
                status,
            ),
        )
        if row is None:
            raise RuntimeError("action proposal insert returned no row")
        return row
