"""Vault-backed, service-scoped secret access."""

from .vault import (
    ACTION_GATEWAY_IDENTITY,
    WEBHOOK_VERIFIER_IDENTITY,
    SecretAccessDenied,
    SecretScope,
    VaultSecretStore,
    vault_action_secret_path,
    vault_webhook_secret_path,
)

__all__ = [
    "ACTION_GATEWAY_IDENTITY",
    "SecretAccessDenied",
    "SecretScope",
    "WEBHOOK_VERIFIER_IDENTITY",
    "VaultSecretStore",
    "vault_action_secret_path",
    "vault_webhook_secret_path",
]
