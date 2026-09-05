"""Authoritative merchant-state verification repository."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from .base import RepositoryError, TenantScopedRepository


class VerificationRepository(TenantScopedRepository):
    def create(
        self,
        *,
        verification_id: str,
        execution_id: str,
        case_id: str,
        observed_resource_state: str,
        verifier_source: str,
        result: str,
        evidence_references: Sequence[str],
        verified_at: datetime,
        canonical_action_id: str | None = None,
        resource_type: str | None = None,
        target_resource: str | None = None,
        verification_method: str = "merchant_state_read",
        verification_version: str = "verification-v1.0.0",
        state_checksum: str | None = None,
        connector_id: str | None = None,
    ) -> object:
        if result not in {"verified_success", "verified_failure", "inconclusive"}:
            raise RepositoryError("verification result is unsupported")
        row = self.fetch_one(
            """
            INSERT INTO public.verifications (
                tenant_id, verification_id, execution_id, case_id,
                canonical_action_id, resource_type, target_resource, connector_id,
                observed_resource_state, verifier_source, verification_method,
                verification_version, result, evidence_references, state_checksum, verified_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING tenant_id, verification_id, execution_id, case_id,
                      canonical_action_id, resource_type, target_resource, connector_id,
                      observed_resource_state, verifier_source, verification_method,
                      verification_version, result, evidence_references, state_checksum, verified_at
            """,
            (
                self.tenant_context.tenant_id,
                verification_id,
                execution_id,
                case_id,
                canonical_action_id,
                resource_type,
                target_resource,
                connector_id,
                observed_resource_state,
                verifier_source,
                verification_method,
                verification_version,
                result,
                json.dumps(list(evidence_references), separators=(",", ":")),
                state_checksum,
                verified_at,
            ),
        )
        if row is None:
            raise RuntimeError("verification insert returned no row")
        return row

    def get(self, *, verification_id: str) -> object | None:
        return self.fetch_one(
            """
            SELECT tenant_id, verification_id, execution_id, case_id,
                   canonical_action_id, resource_type, target_resource, connector_id,
                   observed_resource_state, verifier_source, verification_method,
                   verification_version, result, evidence_references, state_checksum, verified_at
            FROM public.verifications
            WHERE tenant_id = %s AND verification_id = %s
            """,
            (self.tenant_context.tenant_id, verification_id),
        )

    def for_execution(self, *, execution_id: str) -> list[object]:
        return self.fetch_all(
            """
            SELECT tenant_id, verification_id, execution_id, case_id,
                   canonical_action_id, resource_type, target_resource, connector_id,
                   observed_resource_state, verifier_source, verification_method,
                   verification_version, result, evidence_references, state_checksum, verified_at
            FROM public.verifications
            WHERE tenant_id = %s AND execution_id = %s
            ORDER BY verified_at, verification_id
            """,
            (self.tenant_context.tenant_id, execution_id),
        )


__all__ = ["VerificationRepository"]
