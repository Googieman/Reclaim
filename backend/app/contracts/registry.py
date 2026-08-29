"""Compatibility and allowlist checks for tenant-scoped connector contracts."""

from __future__ import annotations

from packages.contracts.connectors import ConnectorManifest, ConnectorType
from packages.contracts.schema_registry import is_compatible


class ContractCompatibilityError(ValueError):
    """Raised when a connector declaration cannot be safely consumed."""


ALLOWED_EVIDENCE_RESOURCES = frozenset(
    {"sessions", "devices", "profile_changes", "orders", "fulfillment", "payments"}
)
ALLOWED_EVIDENCE_OPERATIONS = frozenset({"read"})
ALLOWED_ACTION_OPERATIONS = frozenset(
    {
        "revoke_suspicious_session",
        "hold_fulfillment",
        "cancel_order",
        "refund_payment",
        "restore_identity",
    }
)


def validate_manifest(manifest: ConnectorManifest) -> ConnectorManifest:
    """Validate version, tenant, auth, and explicit operation authority."""

    if not manifest.tenant_id.strip():
        raise ContractCompatibilityError("connector manifest requires tenant scope")
    if not is_compatible(manifest.schema_version) or not is_compatible(manifest.contract_version):
        raise ContractCompatibilityError("connector contract version is incompatible")
    if not manifest.auth_scope or any(not scope.strip() for scope in manifest.auth_scope):
        raise ContractCompatibilityError("connector manifest requires auth scope")

    declarations = (*manifest.resources, *manifest.operations)
    if any(value in {"*", "all", "**"} or "*" in value for value in declarations):
        raise ContractCompatibilityError("wildcard connector authority is not allowed")

    if manifest.connector_type is ConnectorType.EVIDENCE:
        if not set(manifest.resources).issubset(ALLOWED_EVIDENCE_RESOURCES):
            raise ContractCompatibilityError("evidence resource is not allowlisted")
        if not set(manifest.operations).issubset(ALLOWED_EVIDENCE_OPERATIONS):
            raise ContractCompatibilityError("evidence operation is not read-only and allowlisted")
    elif not set(manifest.operations).issubset(ALLOWED_ACTION_OPERATIONS):
        raise ContractCompatibilityError("action operation is not allowlisted")

    return manifest


class ContractRegistry:
    """Tenant-scoped registry of validated connector declarations."""

    def __init__(self) -> None:
        self._manifests: dict[tuple[str, str], ConnectorManifest] = {}

    def register(self, manifest: ConnectorManifest) -> ConnectorManifest:
        validate_manifest(manifest)
        key = (manifest.tenant_id, manifest.connector_id)
        if key in self._manifests:
            raise ContractCompatibilityError("connector is already registered for this tenant")
        self._manifests[key] = manifest
        return manifest

    def get(self, tenant_id: str, connector_id: str) -> ConnectorManifest:
        try:
            return self._manifests[(tenant_id, connector_id)]
        except KeyError as exc:
            raise KeyError(f"unknown connector for tenant: {connector_id}") from exc

    def contains(self, tenant_id: str, connector_id: str) -> bool:
        return (tenant_id, connector_id) in self._manifests

    def for_tenant(self, tenant_id: str) -> tuple[ConnectorManifest, ...]:
        return tuple(
            manifest
            for (registered_tenant, _), manifest in sorted(self._manifests.items())
            if registered_tenant == tenant_id
        )
