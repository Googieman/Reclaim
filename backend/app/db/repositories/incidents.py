"""Incident repository with tenant-scoped duplicate identity."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json

from .base import TenantScopedRepository


class IncidentRepository(TenantScopedRepository):
    def create(
        self,
        *,
        incident_id: str,
        source: str,
        reporter_context: Mapping[str, object],
        received_at: datetime,
        correlation_key: str,
        raw_input_reference: str | None,
        intake_status: str,
        deduplication_identity: str,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO incidents (
                tenant_id, incident_id, source, reporter_context, received_at,
                correlation_key, raw_input_reference, intake_status, deduplication_identity
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
            RETURNING tenant_id, incident_id, source, received_at, correlation_key,
                      intake_status, deduplication_identity, created_at
            """,
            (
                self.tenant_context.tenant_id,
                incident_id,
                source,
                json.dumps(reporter_context, sort_keys=True, separators=(",", ":")),
                received_at,
                correlation_key,
                raw_input_reference,
                intake_status,
                deduplication_identity,
            ),
        )
        if row is None:
            raise RuntimeError("incident insert returned no row")
        return row

    def get(self, *, incident_id: str) -> object | None:
        return self.fetch_one(
            """
            SELECT tenant_id, incident_id, source, reporter_context, received_at,
                   correlation_key, raw_input_reference, intake_status,
                   deduplication_identity, created_at
            FROM incidents
            WHERE tenant_id = %s AND incident_id = %s
            """,
            (self.tenant_context.tenant_id, incident_id),
        )
