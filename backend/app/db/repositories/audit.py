"""Authoritative append-only audit repository."""

from __future__ import annotations

from collections.abc import Sequence

from packages.contracts.audit_replay import AuditRecord

from .base import TenantScopedRepository


class AuditRecordRepository(TenantScopedRepository):
    def latest_checksum(self, *, tenant_id: str) -> str | None:
        self.assert_tenant(tenant_id)
        row = self.fetch_one(
            """
            SELECT record_checksum
            FROM audit_records
            WHERE tenant_id = %s
            ORDER BY chain_sequence DESC
            LIMIT 1
            """,
            (tenant_id,),
        )
        if row is None:
            return None
        return str(row[0])

    def append(self, record: AuditRecord) -> object:
        """Insert exactly the contract fields; no raw payload or secret is accepted."""

        self.assert_tenant(record.tenant_id)
        row = self.fetch_one(
            """
            INSERT INTO audit_records (
                tenant_id, audit_id, case_id, actor, action, input_references,
                output_references, evidence_references, policy_version_id, model_version,
                provider_version, approval_id, execution_id, correlation_ids, outcome,
                recorded_at, previous_record_checksum, record_checksum
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s
            )
            RETURNING tenant_id, audit_id, record_checksum
            """,
            (
                record.tenant_id,
                record.audit_id,
                record.case_id,
                record.actor,
                record.action,
                _as_text_array(record.input_references),
                _as_text_array(record.output_references),
                _as_text_array(record.evidence_references),
                record.policy_version_id,
                record.model_version,
                record.provider_version,
                record.approval_id,
                record.execution_id,
                _as_text_array(record.correlation_ids),
                record.outcome,
                record.recorded_at,
                record.previous_record_checksum,
                record.record_checksum,
            ),
        )
        if row is None:
            raise RuntimeError("audit insert returned no row")
        return row


def _as_text_array(values: Sequence[str]) -> list[str]:
    """Use a driver-native list so psycopg binds a text[] without SQL interpolation."""

    return list(values)
