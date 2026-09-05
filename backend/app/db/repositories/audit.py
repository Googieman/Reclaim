"""Authoritative append-only audit repository."""

from __future__ import annotations

from collections.abc import Sequence

from packages.contracts.audit_replay import AuditRecord

from .base import RepositoryError, TenantScopedRepository


class AuditRecordRepository(TenantScopedRepository):
    def lock_chain(self, *, tenant_id: str) -> None:
        """Serialize audit reads and writes for one tenant until commit/rollback."""

        self.assert_tenant(tenant_id)
        self.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"reclaim.audit-chain:{tenant_id}",),
        )

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

    def checksum_for_audit_id(self, *, tenant_id: str, audit_id: str) -> str | None:
        self.assert_tenant(tenant_id)
        row = self.fetch_one(
            """
            SELECT record_checksum
            FROM audit_records
            WHERE tenant_id = %s AND audit_id = %s
            """,
            (tenant_id, audit_id),
        )
        return None if row is None else str(row[0])

    def list_for_tenant(self, *, tenant_id: str) -> list[object]:
        """Read the append-only chain; this method has no mutation path."""

        self.assert_tenant(tenant_id)
        return self.fetch_all(
            """
            SELECT tenant_id, chain_sequence, audit_id, case_id, actor, action,
                   input_references, output_references, evidence_references,
                   policy_version_id, model_version, provider_version, approval_id,
                   execution_id, correlation_ids, outcome, recorded_at,
                   previous_record_checksum, record_checksum
            FROM public.audit_records
            WHERE tenant_id = %s
            ORDER BY chain_sequence
            """,
            (tenant_id,),
        )

    def for_case(self, *, case_id: str) -> list[object]:
        return self.fetch_all(
            """
            SELECT tenant_id, chain_sequence, audit_id, case_id, actor, action,
                   input_references, output_references, evidence_references,
                   policy_version_id, model_version, provider_version, approval_id,
                   execution_id, correlation_ids, outcome, recorded_at,
                   previous_record_checksum, record_checksum
            FROM public.audit_records
            WHERE tenant_id = %s AND case_id = %s
            ORDER BY chain_sequence
            """,
            (self.tenant_context.tenant_id, case_id),
        )

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
            ON CONFLICT (tenant_id, audit_id) DO NOTHING
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
            existing = self.fetch_one(
                """
                SELECT record_checksum
                FROM audit_records
                WHERE tenant_id = %s AND audit_id = %s
                """,
                (record.tenant_id, record.audit_id),
            )
            if existing is None:
                raise RuntimeError("audit record disappeared after identity conflict")
            if str(existing[0]) != record.record_checksum:
                raise RepositoryError("audit identity conflicts with existing record")
            return existing
        return row


def _as_text_array(values: Sequence[str]) -> list[str]:
    """Use a driver-native list so psycopg binds a text[] without SQL interpolation."""

    return list(values)
