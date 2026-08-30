"""Authoritative deterministic timeline repository."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import json

from .base import TenantScopedRepository


class TimelineEventRepository(TenantScopedRepository):
    def create(
        self,
        *,
        timeline_event_id: str,
        case_id: str,
        canonical_event_type: str,
        source_event_ids: Sequence[str],
        effective_at: datetime,
        ordering_key: str,
        dedupe_key: str,
        event_payload: Mapping[str, object],
        evidence_references: Sequence[str],
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO timeline_events (
                tenant_id, timeline_event_id, case_id, canonical_event_type,
                source_event_ids, effective_at, ordering_key, dedupe_key,
                event_payload, evidence_references
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s::jsonb)
            RETURNING tenant_id, timeline_event_id, case_id, effective_at, ordering_key,
                      dedupe_key
            """,
            (
                self.tenant_context.tenant_id,
                timeline_event_id,
                case_id,
                canonical_event_type,
                json.dumps(list(source_event_ids), separators=(",", ":")),
                effective_at,
                ordering_key,
                dedupe_key,
                json.dumps(event_payload, sort_keys=True, separators=(",", ":")),
                json.dumps(list(evidence_references), separators=(",", ":")),
            ),
        )
        if row is None:
            raise RuntimeError("timeline event insert returned no row")
        return row
