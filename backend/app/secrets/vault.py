"""Vault path and access boundaries for tenant-scoped connector secrets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

ACTION_GATEWAY_IDENTITY = "action-gateway"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


class SecretAccessDenied(PermissionError):
    """Raised when a service asks for a secret outside its policy scope."""


class VaultClient(Protocol):
    def read(self, path: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class SecretScope:
    tenant_id: str
    connector_id: str
    service_identity: str
    purpose: str = "action"

    def __post_init__(self) -> None:
        for name, value in (
            ("tenant_id", self.tenant_id),
            ("connector_id", self.connector_id),
            ("service_identity", self.service_identity),
            ("purpose", self.purpose),
        ):
            if not _SAFE_SEGMENT.fullmatch(value):
                raise ValueError(f"invalid secret scope {name}")


def vault_action_secret_path(tenant_id: str, connector_id: str) -> str:
    scope = SecretScope(tenant_id, connector_id, ACTION_GATEWAY_IDENTITY)
    return f"secret/data/tenants/{scope.tenant_id}/connectors/{scope.connector_id}/action"


class VaultSecretStore:
    """Expose only Action Gateway action credentials to the Action Gateway identity."""

    def __init__(self, client: VaultClient, *, service_identity: str) -> None:
        self.client = client
        self.service_identity = service_identity

    @classmethod
    def from_address(cls, address: str, *, token: str, service_identity: str) -> VaultSecretStore:
        import hvac

        client = hvac.Client(url=address, token=token)
        return cls(_HvacClient(client), service_identity=service_identity)

    def read_action_connector_secret(self, *, tenant_id: str, connector_id: str) -> dict[str, Any]:
        if self.service_identity != ACTION_GATEWAY_IDENTITY:
            raise SecretAccessDenied("only the Action Gateway may read action connector secrets")
        data = self.client.read(vault_action_secret_path(tenant_id, connector_id))
        if not data:
            raise SecretAccessDenied("action connector secret is unavailable")
        return dict(data)


class _HvacClient:
    def __init__(self, client: Any) -> None:
        self.client = client

    def read(self, path: str) -> dict[str, Any] | None:
        response = self.client.read(path)
        if not response:
            return None
        data = response.get("data", {})
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            return dict(data["data"])
        return dict(data) if isinstance(data, dict) else None
