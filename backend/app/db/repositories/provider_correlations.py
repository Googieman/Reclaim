"""Authoritative PostgreSQL provider-correlation mappings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from packages.contracts.intake import VerifiedProviderCorrelation

from app.auth.oidc import IdentityType

from .base import RepositoryError, TenantScopedRepository


@dataclass(frozen=True, slots=True)
class ProviderCorrelationMapping:
    tenant_id: str
    mapping_id: str
    correlation_schema_version: str
    provider: str
    connector_id: str
    provider_event_id: str | None
    provider_payment_id: str | None
    provider_order_id: str | None
    merchant_reference: str | None
    incident_id: str
    case_id: str
    related_order_reference: str | None
    related_payment_reference: str | None
    mapping_source: str
    mapping_source_reference: str
    mapping_source_checksum: str
    mapping_status: str
    created_at: datetime
    verified_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProviderCorrelationResolution:
    mapping: ProviderCorrelationMapping | None
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.mapping is not None and self.reason is None


class ProviderCorrelationMappingConflictError(RepositoryError):
    """Raised when a mapping identity is reused with different content."""


class ProviderCorrelationRepository(TenantScopedRepository):
    """Read mappings only inside the authenticated PostgreSQL tenant context."""

    _SELECT_COLUMNS = """
        tenant_id, mapping_id, correlation_schema_version, provider, connector_id,
        provider_event_id, provider_payment_id, provider_order_id, merchant_reference,
        incident_id, case_id, related_order_reference, related_payment_reference,
        mapping_source, mapping_source_reference, mapping_source_checksum,
        mapping_status, created_at, verified_at, revoked_at
    """

    def register(
        self,
        *,
        mapping_id: str,
        provider: str,
        connector_id: str,
        provider_event_id: str | None = None,
        provider_payment_id: str | None = None,
        provider_order_id: str | None = None,
        merchant_reference: str | None = None,
        incident_id: str,
        case_id: str,
        related_order_reference: str | None = None,
        related_payment_reference: str | None = None,
        mapping_source: str,
        mapping_source_reference: str,
        mapping_source_checksum: str,
        verified_at: datetime,
    ) -> tuple[ProviderCorrelationMapping, bool]:
        """Register trusted merchant context; webhook processing never calls this."""

        if self.tenant_context.authorization_context.identity_type is not IdentityType.SERVICE:
            raise RepositoryError("provider mappings can only be provisioned by a service identity")
        values = _validated_mapping_values(
            mapping_id=mapping_id,
            provider=provider,
            connector_id=connector_id,
            provider_event_id=provider_event_id,
            provider_payment_id=provider_payment_id,
            provider_order_id=provider_order_id,
            merchant_reference=merchant_reference,
            incident_id=incident_id,
            case_id=case_id,
            related_order_reference=related_order_reference,
            related_payment_reference=related_payment_reference,
            mapping_source=mapping_source,
            mapping_source_reference=mapping_source_reference,
            mapping_source_checksum=mapping_source_checksum,
        )
        row = self.fetch_one(
            f"""
            INSERT INTO provider_correlation_mappings (
                tenant_id, mapping_id, correlation_schema_version, provider, connector_id,
                provider_event_id, provider_payment_id, provider_order_id,
                merchant_reference, incident_id, case_id, related_order_reference,
                related_payment_reference, mapping_source, mapping_source_reference,
                mapping_source_checksum, mapping_status, verified_at
            )
            VALUES (%s, %s, '1.0.0', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, 'active', %s)
            ON CONFLICT DO NOTHING
            RETURNING {self._SELECT_COLUMNS}
            """,
            (
                self.tenant_context.tenant_id,
                values["mapping_id"],
                values["provider"],
                values["connector_id"],
                values["provider_event_id"],
                values["provider_payment_id"],
                values["provider_order_id"],
                values["merchant_reference"],
                values["incident_id"],
                values["case_id"],
                values["related_order_reference"],
                values["related_payment_reference"],
                values["mapping_source"],
                values["mapping_source_reference"],
                values["mapping_source_checksum"],
                verified_at,
            ),
        )
        if row is not None:
            return _mapping_from_row(row), True

        existing = self.get(mapping_id=mapping_id)
        if existing is not None:
            if not _same_registered_mapping(existing, values, verified_at):
                raise ProviderCorrelationMappingConflictError(
                    "provider mapping identity already exists with different content"
                )
            return existing, False

        existing = self._get_active_by_identity(values)
        if existing is None:
            raise ProviderCorrelationMappingConflictError(
                "provider correlation identity is already owned outside this tenant"
            )
        if not _same_mapping_content(existing, values, verified_at):
            raise ProviderCorrelationMappingConflictError(
                "provider correlation identity already maps to different content"
            )
        return existing, False

    def _get_active_by_identity(
        self, values: dict[str, str | None]
    ) -> ProviderCorrelationMapping | None:
        row = self.fetch_one(
            f"""
            SELECT {self._SELECT_COLUMNS}
            FROM provider_correlation_mappings
            WHERE tenant_id = %s
              AND provider = %s
              AND connector_id = %s
              AND mapping_status = 'active'
              AND (
                  provider_event_id = %s
                  OR provider_payment_id = %s
                  OR provider_order_id = %s
                  OR merchant_reference = %s
              )
            ORDER BY mapping_id
            LIMIT 1
            """,
            (
                self.tenant_context.tenant_id,
                values["provider"],
                values["connector_id"],
                values["provider_event_id"],
                values["provider_payment_id"],
                values["provider_order_id"],
                values["merchant_reference"],
            ),
        )
        return None if row is None else _mapping_from_row(row)

    def get(self, *, mapping_id: str) -> ProviderCorrelationMapping | None:
        row = self.fetch_one(
            f"""
            SELECT {self._SELECT_COLUMNS}
            FROM provider_correlation_mappings
            WHERE tenant_id = %s AND mapping_id = %s
            """,
            (self.tenant_context.tenant_id, mapping_id),
        )
        return None if row is None else _mapping_from_row(row)

    def resolve(self, correlation: VerifiedProviderCorrelation) -> ProviderCorrelationResolution:
        """Resolve all verified identifiers to one active mapping, never caller IDs."""

        rows = self.fetch_all(
            f"""
            SELECT {self._SELECT_COLUMNS}
            FROM provider_correlation_mappings
            WHERE tenant_id = %s
              AND provider = %s
              AND connector_id = %s
              AND (
                  provider_event_id = %s
                  OR provider_payment_id = %s
                  OR provider_order_id = %s
                  OR merchant_reference = %s
              )
            ORDER BY mapping_id
            """,
            (
                self.tenant_context.tenant_id,
                correlation.provider,
                correlation.connector_id,
                correlation.provider_event_id,
                correlation.provider_payment_id,
                correlation.provider_order_id,
                correlation.merchant_reference,
            ),
        )
        mappings = [_mapping_from_row(row) for row in rows]
        active = [mapping for mapping in mappings if mapping.mapping_status == "active"]
        if not active:
            if mappings:
                return ProviderCorrelationResolution(None, "revoked_mapping")
            return ProviderCorrelationResolution(None, "unresolved_association")

        matches = [mapping for mapping in active if _matches_all_identifiers(correlation, mapping)]
        if len(matches) == 1:
            mapping = matches[0]
            if mapping.tenant_id != self.tenant_context.tenant_id:
                return ProviderCorrelationResolution(None, "cross_tenant")
            return ProviderCorrelationResolution(mapping)
        if len(matches) > 1:
            return ProviderCorrelationResolution(None, "ambiguous_mapping")
        return ProviderCorrelationResolution(None, "mapping_conflict")

    def revoke(self, *, mapping_id: str, revoked_at: datetime) -> ProviderCorrelationMapping:
        row = self.fetch_one(
            f"""
            UPDATE provider_correlation_mappings
            SET mapping_status = 'revoked', revoked_at = %s
            WHERE tenant_id = %s AND mapping_id = %s AND mapping_status = 'active'
            RETURNING {self._SELECT_COLUMNS}
            """,
            (revoked_at, self.tenant_context.tenant_id, mapping_id),
        )
        if row is None:
            raise RepositoryError("active provider mapping does not exist for this tenant")
        return _mapping_from_row(row)


def _validated_mapping_values(**values: str | None) -> dict[str, str | None]:
    for name in (
        "mapping_id",
        "provider",
        "connector_id",
        "incident_id",
        "case_id",
        "mapping_source",
        "mapping_source_reference",
        "mapping_source_checksum",
    ):
        value = values.get(name)
        if not isinstance(value, str) or not value.strip():
            raise RepositoryError(f"provider mapping {name} is required")
        values[name] = value.strip()
    for name in (
        "provider_event_id",
        "provider_payment_id",
        "provider_order_id",
        "merchant_reference",
        "related_order_reference",
        "related_payment_reference",
    ):
        value = values.get(name)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise RepositoryError(f"provider mapping {name} cannot be blank")
            values[name] = value.strip()
    if not any(
        values.get(name)
        for name in ("provider_event_id", "provider_payment_id", "provider_order_id")
    ):
        raise RepositoryError("provider mapping needs a provider-native identity")
    return values


def _same_registered_mapping(
    existing: ProviderCorrelationMapping,
    values: dict[str, str | None],
    verified_at: datetime,
) -> bool:
    return existing.mapping_id == values["mapping_id"] and _same_mapping_content(
        existing, values, verified_at
    )


def _same_mapping_content(
    existing: ProviderCorrelationMapping,
    values: dict[str, str | None],
    verified_at: datetime,
) -> bool:
    return (
        all(
            getattr(existing, name) == values.get(name)
            for name in (
                "provider",
                "connector_id",
                "provider_event_id",
                "provider_payment_id",
                "provider_order_id",
                "merchant_reference",
                "incident_id",
                "case_id",
                "related_order_reference",
                "related_payment_reference",
                "mapping_source",
                "mapping_source_reference",
                "mapping_source_checksum",
            )
        )
        and existing.mapping_status == "active"
        and existing.verified_at == verified_at
    )


def _matches_all_identifiers(
    correlation: VerifiedProviderCorrelation, mapping: ProviderCorrelationMapping
) -> bool:
    if mapping.provider != correlation.provider or mapping.connector_id != correlation.connector_id:
        return False
    if (
        mapping.provider_event_id is not None
        and mapping.provider_event_id != correlation.provider_event_id
    ):
        return False
    if (
        correlation.provider_payment_id is not None
        and mapping.provider_payment_id != correlation.provider_payment_id
    ):
        return False
    if (
        correlation.provider_order_id is not None
        and mapping.provider_order_id != correlation.provider_order_id
    ):
        return False
    if (
        correlation.merchant_reference is not None
        and mapping.merchant_reference != correlation.merchant_reference
    ):
        return False
    return True


def _mapping_from_row(row: Any) -> ProviderCorrelationMapping:
    return ProviderCorrelationMapping(
        tenant_id=str(row[0]),
        mapping_id=str(row[1]),
        correlation_schema_version=str(row[2]),
        provider=str(row[3]),
        connector_id=str(row[4]),
        provider_event_id=None if row[5] is None else str(row[5]),
        provider_payment_id=None if row[6] is None else str(row[6]),
        provider_order_id=None if row[7] is None else str(row[7]),
        merchant_reference=None if row[8] is None else str(row[8]),
        incident_id=str(row[9]),
        case_id=str(row[10]),
        related_order_reference=None if row[11] is None else str(row[11]),
        related_payment_reference=None if row[12] is None else str(row[12]),
        mapping_source=str(row[13]),
        mapping_source_reference=str(row[14]),
        mapping_source_checksum=str(row[15]),
        mapping_status=str(row[16]),
        created_at=row[17],
        verified_at=row[18],
        revoked_at=row[19],
    )


def correlation_to_json(correlation: VerifiedProviderCorrelation | None) -> str | None:
    if correlation is None:
        return None
    return json.dumps(correlation.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def correlation_from_json(value: object) -> VerifiedProviderCorrelation | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RepositoryError("persisted provider correlation is not an object")
    return VerifiedProviderCorrelation.model_validate(value)
