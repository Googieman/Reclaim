"""Incident repository with tenant-scoped duplicate identity."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .base import RepositoryError, TenantScopedRepository


@dataclass(frozen=True, slots=True)
class IncidentCreateResult:
    """The incident row and whether this transaction created its identity."""

    row: Any
    inserted: bool


class IncidentRepository(TenantScopedRepository):
    def create_or_get(
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
    ) -> IncidentCreateResult:
        row = self.fetch_one(
            """
            INSERT INTO incidents (
                tenant_id, incident_id, source, reporter_context, received_at,
                correlation_key, raw_input_reference, intake_status, deduplication_identity
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, deduplication_identity) DO NOTHING
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
        if row is not None:
            return IncidentCreateResult(row=row, inserted=True)

        existing = self.find_by_deduplication_identity(
            deduplication_identity=deduplication_identity
        )
        if existing is None:
            raise RepositoryError("incident identity conflicts with existing non-duplicate data")
        return IncidentCreateResult(row=existing, inserted=False)

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
        return self.create_or_get(
            incident_id=incident_id,
            source=source,
            reporter_context=reporter_context,
            received_at=received_at,
            correlation_key=correlation_key,
            raw_input_reference=raw_input_reference,
            intake_status=intake_status,
            deduplication_identity=deduplication_identity,
        ).row

    def find_by_deduplication_identity(self, *, deduplication_identity: str) -> object | None:
        if not deduplication_identity.strip():
            raise RepositoryError("deduplication identity is required")
        return self.fetch_one(
            """
            SELECT tenant_id, incident_id, source, received_at, correlation_key,
                   intake_status, deduplication_identity, created_at
            FROM incidents
            WHERE tenant_id = %s AND deduplication_identity = %s
            """,
            (self.tenant_context.tenant_id, deduplication_identity),
        )

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
