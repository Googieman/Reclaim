"""Authoritative unresolved-case escalation repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import json

from .base import TenantScopedRepository


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
        state: str = "open",
        created_at: datetime | None = None,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO escalations (
                tenant_id, escalation_id, case_id, owner, reason,
                remaining_exposure_minor, evidence_references,
                recommended_human_decision, state, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, COALESCE(%s, now()))
            RETURNING tenant_id, escalation_id, case_id, owner, state, created_at
            """,
            (
                self.tenant_context.tenant_id,
                escalation_id,
                case_id,
                owner,
                reason,
                remaining_exposure_minor,
                json.dumps(list(evidence_references), separators=(",", ":")),
                recommended_human_decision,
                state,
                created_at,
            ),
        )
        if row is None:
            raise RuntimeError("escalation insert returned no row")
        return row
