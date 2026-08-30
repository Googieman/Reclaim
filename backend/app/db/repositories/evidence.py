"""Authoritative normalized evidence metadata repository."""

from __future__ import annotations

from datetime import datetime
import json

from .base import TenantScopedRepository


class EvidenceItemRepository(TenantScopedRepository):
    def create(
        self,
        *,
        evidence_id: str,
        case_id: str,
        connector_id: str,
        resource_type: str,
        source_identifier: str,
        observed_at: datetime | None,
        received_at: datetime,
        raw_object_uri: str | None,
        checksum: str | None,
        normalization_status: str,
        completeness: str,
        trust_classification: str,
        collection_error: str | None,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO evidence_items (
                tenant_id, evidence_id, case_id, connector_id, resource_type,
                source_identifier, observed_at, received_at, raw_object_uri, checksum,
                normalization_status, completeness, trust_classification, collection_error
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING tenant_id, evidence_id, case_id, connector_id, resource_type,
                      source_identifier, completeness, checksum
            """,
            (
                self.tenant_context.tenant_id,
                evidence_id,
                case_id,
                connector_id,
                resource_type,
                source_identifier,
                observed_at,
                received_at,
                raw_object_uri,
                checksum,
                normalization_status,
                completeness,
                trust_classification,
                collection_error,
            ),
        )
        if row is None:
            raise RuntimeError("evidence insert returned no row")
        return row
