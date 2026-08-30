"""Declaration-only tenant registries.

These registries describe approved configuration.  They do not expose connector
clients, credentials, arbitrary network calls, or mutation capabilities.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from packages.contracts.connectors import ConnectorManifest


@dataclass(frozen=True, slots=True)
class ConnectorDeclaration:
    tenant_id: str
    connector_id: str
    manifest: ConnectorManifest
    enabled: bool = True

    def __post_init__(self) -> None:
        if (
            self.manifest.tenant_id != self.tenant_id
            or self.manifest.connector_id != self.connector_id
        ):
            raise ValueError("connector declaration identity does not match its manifest")


@dataclass(frozen=True, slots=True)
class RoleDeclaration:
    tenant_id: str
    subject: str
    roles: frozenset[str]

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.subject.strip() or not self.roles:
            raise ValueError("role declarations require tenant, subject, and roles")


class ConnectorRegistry:
    def __init__(self, declarations: Iterable[ConnectorDeclaration] = ()) -> None:
        self._declarations: dict[tuple[str, str], ConnectorDeclaration] = {}
        for declaration in declarations:
            self.register(declaration)

    def register(self, declaration: ConnectorDeclaration) -> None:
        key = (declaration.tenant_id, declaration.connector_id)
        if key in self._declarations:
            raise ValueError("connector declaration already exists")
        self._declarations[key] = declaration

    def get(self, *, tenant_id: str, connector_id: str) -> ConnectorDeclaration:
        try:
            return self._declarations[(tenant_id, connector_id)]
        except KeyError as exc:
            raise KeyError("connector declaration is not registered for this tenant") from exc

    def for_tenant(self, tenant_id: str) -> tuple[ConnectorDeclaration, ...]:
        return tuple(
            declaration
            for (registered_tenant, _), declaration in sorted(self._declarations.items())
            if registered_tenant == tenant_id
        )

    def allows(self, *, tenant_id: str, connector_id: str, operation: str) -> bool:
        declaration = self.get(tenant_id=tenant_id, connector_id=connector_id)
        return declaration.enabled and operation in declaration.manifest.operations


class PolicyOwnerRegistry:
    def __init__(self) -> None:
        self._owners: dict[str, frozenset[str]] = {}

    def register(self, *, tenant_id: str, subjects: Iterable[str]) -> None:
        owners = frozenset(subject for subject in subjects if subject.strip())
        if not tenant_id.strip() or not owners:
            raise ValueError("policy-owner declaration requires tenant and subject")
        self._owners[tenant_id] = owners

    def is_owner(self, *, tenant_id: str, subject: str) -> bool:
        return subject in self._owners.get(tenant_id, frozenset())


class RoleRegistry:
    def __init__(self, declarations: Iterable[RoleDeclaration] = ()) -> None:
        self._roles: dict[tuple[str, str], RoleDeclaration] = {}
        for declaration in declarations:
            self.register(declaration)

    def register(self, declaration: RoleDeclaration) -> None:
        key = (declaration.tenant_id, declaration.subject)
        if key in self._roles:
            raise ValueError("role declaration already exists")
        self._roles[key] = declaration

    def roles_for(self, *, tenant_id: str, subject: str) -> frozenset[str]:
        declaration = self._roles.get((tenant_id, subject))
        return frozenset() if declaration is None else declaration.roles
