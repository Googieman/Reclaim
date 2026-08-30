"""Vault action-secret scope tests."""

import os

import pytest
from app.secrets.vault import (
    ACTION_GATEWAY_IDENTITY,
    SecretAccessDenied,
    VaultSecretStore,
    vault_action_secret_path,
)


class FakeVault:
    def __init__(self) -> None:
        self.reads: list[str] = []

    def read(self, path: str) -> dict[str, str]:
        self.reads.append(path)
        return {"api_key": "test-only-runtime-value"}


def test_only_action_gateway_can_read_action_connector_secret() -> None:
    fake = FakeVault()
    store = VaultSecretStore(fake, service_identity=ACTION_GATEWAY_IDENTITY)
    assert store.read_action_connector_secret(
        tenant_id="tenant-a", connector_id="payments"
    ) == {"api_key": "test-only-runtime-value"}
    assert fake.reads == [vault_action_secret_path("tenant-a", "payments")]

    with pytest.raises(SecretAccessDenied, match="only the Action Gateway"):
        VaultSecretStore(
            fake, service_identity="model-gateway"
        ).read_action_connector_secret(tenant_id="tenant-a", connector_id="payments")


def test_live_vault_action_scope_if_configured() -> None:
    address = os.getenv("RECLAIM_VAULT_ADDR")
    token = os.getenv("RECLAIM_VAULT_TOKEN")
    if not (address and token):
        pytest.skip("Vault address and scoped token are required for live validation")
    store = VaultSecretStore.from_address(
        address,
        token=token,
        service_identity=ACTION_GATEWAY_IDENTITY,
    )
    assert (
        store.read_action_connector_secret(
            tenant_id="tenant-a", connector_id="payments"
        )["api_key"]
        == "test-only-runtime-value"
    )
