"""Vault-backed, service-scoped secret access."""

from .vault import (
    ACTION_GATEWAY_IDENTITY,
    SecretAccessDenied,
    SecretScope,
    VaultSecretStore,
    vault_action_secret_path,
)

__all__ = [
    "ACTION_GATEWAY_IDENTITY",
    "SecretAccessDenied",
    "SecretScope",
    "VaultSecretStore",
    "vault_action_secret_path",
]
