"""Authoritative connector declaration repository."""

from __future__ import annotations

from collections.abc import Sequence
import json

from .base import TenantScopedRepository


class ConnectorConfigurationRepository(TenantScopedRepository):
    def create(
        self,
        *,
        connector_id: str,
        contract_version: str,
        connector_type: str,
        allowed_resources: Sequence[str],
        allowed_operations: Sequence[str],
        auth_scope: Sequence[str],
        credential_scope_ref: str,
        schema_version: str,
        failure_state_version: str,
        mode: str,
        enabled: bool = True,
    ) -> object:
        row = self.fetch_one(
            """
            INSERT INTO connector_configurations (
                tenant_id, connector_id, contract_version, connector_type,
                allowed_resources, allowed_operations, auth_scope,
                credential_scope_ref, schema_version, failure_state_version, mode, enabled
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s)
            RETURNING tenant_id, connector_id, contract_version, connector_type, mode, enabled
            """,
            (
                self.tenant_context.tenant_id,
                connector_id,
                contract_version,
                connector_type,
                json.dumps(list(allowed_resources), separators=(",", ":")),
                json.dumps(list(allowed_operations), separators=(",", ":")),
                list(auth_scope),
                credential_scope_ref,
                schema_version,
                failure_state_version,
                mode,
                enabled,
            ),
        )
        if row is None:
            raise RuntimeError("connector configuration insert returned no row")
        return row
