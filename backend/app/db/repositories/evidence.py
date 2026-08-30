"""Authoritative normalized evidence metadata repository."""

from __future__ import annotations

from datetime import datetime

from .base import TenantScopedRepository


class EvidenceItemRepository(TenantScopedRepository):
    def create_or_get(
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
        """Insert immutable evidence metadata and return an existing duplicate."""

        row = self.fetch_one(
            """
            INSERT INTO evidence_items (
                tenant_id, evidence_id, case_id, connector_id, resource_type,
                source_identifier, observed_at, received_at, raw_object_uri, checksum,
                normalization_status, completeness, trust_classification, collection_error
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, evidence_id) DO NOTHING
            RETURNING tenant_id, evidence_id, case_id, connector_id, resource_type,
                      completeness, checksum
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
        if row is not None:
            return row
        existing = self.fetch_one(
            """
            SELECT tenant_id, evidence_id, case_id, connector_id, resource_type,
                   completeness, checksum
            FROM evidence_items
            WHERE tenant_id = %s AND evidence_id = %s
            """,
            (self.tenant_context.tenant_id, evidence_id),
        )
        if existing is None:
            raise RuntimeError("evidence identity conflicts with existing data")
        return existing

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
        return self.create_or_get(
            evidence_id=evidence_id,
            case_id=case_id,
            connector_id=connector_id,
            resource_type=resource_type,
            source_identifier=source_identifier,
            observed_at=observed_at,
            received_at=received_at,
            raw_object_uri=raw_object_uri,
            checksum=checksum,
            normalization_status=normalization_status,
            completeness=completeness,
            trust_classification=trust_classification,
            collection_error=collection_error,
        )

    def for_case(self, *, case_id: str) -> list[object]:
        """Return tenant-scoped evidence metadata in stable source order."""

        if not case_id.strip():
            raise ValueError("case_id is required")
        return self.fetch_all(
            """
            SELECT tenant_id, evidence_id, case_id, connector_id, resource_type,
                   source_identifier, observed_at, received_at, raw_object_uri, checksum,
                   normalization_status, completeness, trust_classification, collection_error
            FROM evidence_items
            WHERE tenant_id = %s AND case_id = %s
            ORDER BY resource_type, connector_id, evidence_id
            """,
            (self.tenant_context.tenant_id, case_id),
        )
