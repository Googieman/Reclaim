"""Authoritative deterministic timeline repository."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from .base import TenantScopedRepository


class TimelineEventRepository(TenantScopedRepository):
    def upsert(
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
        """Insert or converge a derived event identified by its case/dedupe key."""

        row = self.fetch_one(
            """
            INSERT INTO timeline_events (
                tenant_id, timeline_event_id, case_id, canonical_event_type,
                source_event_ids, effective_at, ordering_key, dedupe_key,
                event_payload, evidence_references
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s::jsonb)
            ON CONFLICT (tenant_id, case_id, dedupe_key) DO UPDATE SET
                timeline_event_id = EXCLUDED.timeline_event_id,
                canonical_event_type = EXCLUDED.canonical_event_type,
                source_event_ids = EXCLUDED.source_event_ids,
                effective_at = EXCLUDED.effective_at,
                ordering_key = EXCLUDED.ordering_key,
                event_payload = EXCLUDED.event_payload,
                evidence_references = EXCLUDED.evidence_references
            RETURNING tenant_id, timeline_event_id, case_id, effective_at, ordering_key,
                      dedupe_key
            """,
            (
                self.tenant_context.tenant_id,
                timeline_event_id,
                case_id,
                canonical_event_type,
                json.dumps(sorted(set(source_event_ids)), separators=(",", ":")),
                effective_at,
                ordering_key,
                dedupe_key,
                json.dumps(event_payload, sort_keys=True, separators=(",", ":")),
                json.dumps(sorted(set(evidence_references)), separators=(",", ":")),
            ),
        )
        if row is None:
            raise RuntimeError("timeline event upsert returned no row")
        return row

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
        return self.upsert(
            timeline_event_id=timeline_event_id,
            case_id=case_id,
            canonical_event_type=canonical_event_type,
            source_event_ids=source_event_ids,
            effective_at=effective_at,
            ordering_key=ordering_key,
            dedupe_key=dedupe_key,
            event_payload=event_payload,
            evidence_references=evidence_references,
        )

    def for_case(self, *, case_id: str) -> list[object]:
        """Return tenant-scoped canonical events in their persisted order."""

        if not case_id.strip():
            raise ValueError("case_id is required")
        return self.fetch_all(
            """
            SELECT tenant_id, timeline_event_id, case_id, canonical_event_type,
                   source_event_ids, effective_at, ordering_key, dedupe_key,
                   event_payload, evidence_references
            FROM timeline_events
            WHERE tenant_id = %s AND case_id = %s
            ORDER BY effective_at, ordering_key
            """,
            (self.tenant_context.tenant_id, case_id),
        )
