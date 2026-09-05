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
        incident_type: str | None = None,
        occurred_at: datetime | None = None,
        narrative_checksum: str | None = None,
        customer_reference: str | None = None,
        account_reference: str | None = None,
        order_reference: str | None = None,
        payment_reference: str | None = None,
        reported_amount_minor: int | None = None,
        reported_currency: str | None = None,
        external_reference: str | None = None,
    ) -> IncidentCreateResult:
        row = self.fetch_one(
            """
            INSERT INTO incidents (
                tenant_id, incident_id, source, reporter_context, received_at,
                correlation_key, raw_input_reference, intake_status, deduplication_identity,
                incident_type, occurred_at, narrative_checksum, customer_reference,
                account_reference, order_reference, payment_reference,
                reported_amount_minor, reported_currency, external_reference
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, deduplication_identity) DO NOTHING
            RETURNING tenant_id, incident_id, source, received_at, correlation_key,
                      intake_status, deduplication_identity, created_at,
                      incident_type, occurred_at, narrative_checksum, customer_reference,
                      account_reference, order_reference, payment_reference,
                      reported_amount_minor, reported_currency, external_reference
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
                incident_type,
                occurred_at,
                narrative_checksum,
                customer_reference,
                account_reference,
                order_reference,
                payment_reference,
                reported_amount_minor,
                reported_currency,
                external_reference,
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
                   intake_status, deduplication_identity, created_at,
                   incident_type, occurred_at, narrative_checksum, customer_reference,
                   account_reference, order_reference, payment_reference,
                   reported_amount_minor, reported_currency, external_reference
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
                   deduplication_identity, created_at,
                   incident_type, occurred_at, narrative_checksum, customer_reference,
                   account_reference, order_reference, payment_reference,
                   reported_amount_minor, reported_currency, external_reference
            FROM incidents
            WHERE tenant_id = %s AND incident_id = %s
            """,
            (self.tenant_context.tenant_id, incident_id),
        )
