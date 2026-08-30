"""Authoritative advisory attribution repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import json

from .base import TenantScopedRepository


class AttributionRepository(TenantScopedRepository):
    def create(
        self,
        *,
        attribution_id: str,
        timeline_event_id: str,
        label: str,
        confidence: float,
        rationale: str,
        method: str,
        model_or_rules_version: str,
        evidence_references: Sequence[str],
        created_at: datetime | None = None,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO attributions (
                tenant_id, attribution_id, timeline_event_id, label, confidence,
                rationale, method, model_or_rules_version, evidence_references, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, COALESCE(%s, now()))
            RETURNING tenant_id, attribution_id, timeline_event_id, label, confidence
            """,
            (
                self.tenant_context.tenant_id,
                attribution_id,
                timeline_event_id,
                label,
                confidence,
                rationale,
                method,
                model_or_rules_version,
                json.dumps(list(evidence_references), separators=(",", ":")),
                created_at,
            ),
        )
        if row is None:
            raise RuntimeError("attribution insert returned no row")
        return row
