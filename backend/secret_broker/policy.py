"""Installed identity-to-secret policy for the private broker."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

_SECRET_ID = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_IDENTITY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PolicyDenied(PermissionError):
    """Raised for every unknown or unauthorized identity/secret combination."""


@dataclass(frozen=True, slots=True)
class IdentityGrant:
    identity: str
    certificate_uri_san: str
    tenants: frozenset[str]
    secret_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not _IDENTITY.fullmatch(self.identity) or not self.certificate_uri_san.startswith(
            "spiffe://reclaim/"
        ):
            raise ValueError("invalid broker identity grant")
        if any(not tenant.strip() for tenant in self.tenants):
            raise ValueError("identity grant contains an invalid tenant")
        if any(not _SECRET_ID.fullmatch(secret_id) for secret_id in self.secret_ids):
            raise ValueError("identity grant contains an invalid secret ID")


@dataclass(frozen=True, slots=True)
class SecretDefinition:
    secret_id: str
    scope: Literal["tenant", "service"]
    vault_path: str
    cache_ttl_seconds: int
    identities: frozenset[str]

    def __post_init__(self) -> None:
        if not _SECRET_ID.fullmatch(self.secret_id):
            raise ValueError("invalid secret ID")
        if not self.vault_path.startswith("secret/data/") or ".." in self.vault_path.split("/"):
            raise ValueError("invalid Vault path")
        max_ttl = 60 if self.secret_id.endswith(".action") else 300
        if not 1 <= self.cache_ttl_seconds <= max_ttl:
            raise ValueError(f"cache TTL must be between 1 and {max_ttl} seconds")
        if not self.identities or any(not _IDENTITY.fullmatch(item) for item in self.identities):
            raise ValueError("secret definition must name valid identities")


@dataclass(frozen=True, slots=True)
class SecretPolicy:
    identities: tuple[IdentityGrant, ...]
    secrets: tuple[SecretDefinition, ...]

    def __post_init__(self) -> None:
        identity_names = [item.identity for item in self.identities]
        secret_names = [item.secret_id for item in self.secrets]
        if len(identity_names) != len(set(identity_names)):
            raise ValueError("duplicate broker identity")
        if len(secret_names) != len(set(secret_names)):
            raise ValueError("duplicate broker secret")
        known_identities = set(identity_names)
        for secret in self.secrets:
            if not secret.identities <= known_identities:
                raise ValueError("secret references an unknown identity")

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> SecretPolicy:
        if document.get("template_only") is True:
            raise ValueError("template_only policy cannot be installed")
        if document.get("default_effect") != "deny":
            raise ValueError("broker policy must default to deny")
        identities = tuple(
            IdentityGrant(
                identity=item["identity"],
                certificate_uri_san=item["certificate_uri_san"],
                tenants=frozenset(item.get("allowed_tenants", [])),
                secret_ids=frozenset(item.get("secret_ids", [])),
            )
            for item in document.get("identities", [])
        )
        secret_records = {item["id"]: item for item in document.get("secrets", [])}
        definitions = tuple(
            SecretDefinition(
                secret_id=secret_id,
                scope=record["scope"],
                vault_path=record["vault_kv_v2_path"],
                cache_ttl_seconds=record["cache_ttl_seconds"],
                identities=frozenset(
                    grant.identity for grant in identities if secret_id in grant.secret_ids
                ),
            )
            for secret_id, record in secret_records.items()
        )
        return cls(identities=identities, secrets=definitions)

    def authorize(
        self, identity_uri: str, secret_id: str, tenant_id: str | None
    ) -> tuple[SecretDefinition, str | None]:
        grant = next(
            (item for item in self.identities if item.certificate_uri_san == identity_uri),
            None,
        )
        definition = next((item for item in self.secrets if item.secret_id == secret_id), None)
        if grant is None or definition is None or grant.identity not in definition.identities:
            raise PolicyDenied("secret access forbidden")
        if definition.scope == "service":
            if tenant_id is not None:
                raise PolicyDenied("secret access forbidden")
            return definition, None
        if tenant_id is None or tenant_id not in grant.tenants:
            raise PolicyDenied("secret access forbidden")
        return definition, tenant_id
