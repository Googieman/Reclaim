"""Security boundary tests for broker policy and deployment artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from secret_broker.contracts import SecretRequest
from secret_broker.policy import IdentityGrant, SecretDefinition, SecretPolicy
from secret_broker.service import SecretBrokerService


ROOT = Path(__file__).resolve().parents[2]


def test_example_policy_is_not_installable() -> None:
    document = __import__("json").loads(
        (ROOT / "secrets" / "access-policy.example.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ValueError, match="template_only"):
        SecretPolicy.from_document(document)


def test_broker_policy_cannot_be_bypassed_by_a_client_selected_vault_path() -> None:
    class Vault:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def read(self, path: str) -> dict[str, str]:
            self.paths.append(path)
            return {"value": "canary"}

    policy = SecretPolicy(
        identities=(
            IdentityGrant(
                identity="intake-api",
                certificate_uri_san="spiffe://reclaim/final/intake-api",
                tenants=frozenset({"tenant-a"}),
                secret_ids=frozenset({"api.evidence"}),
            ),
        ),
        secrets=(
            SecretDefinition(
                secret_id="api.evidence",
                scope="tenant",
                vault_path="secret/data/reclaim/final/tenants/tenant-a/api/evidence",
                cache_ttl_seconds=300,
                identities=frozenset({"intake-api"}),
            ),
        ),
    )
    vault = Vault()
    service = SecretBrokerService(policy, vault=vault, audit=lambda **_: None)

    service.resolve(
        identity_uri="spiffe://reclaim/final/intake-api",
        request=SecretRequest(secret_id="api.evidence", tenant_id="tenant-a"),
        request_id="request-path-override",
    )
    assert vault.paths == ["secret/data/reclaim/final/tenants/tenant-a/api/evidence"]
