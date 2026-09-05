"""Phase 1 production identity, secret, and broker security contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.config import Settings
from app.events.outbox_relay import _default_producer_kwargs
from app.secrets.vault import SecretAccessDenied, VaultSecretStore

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"


def test_production_settings_require_asymmetric_oidc_and_vault_tls() -> None:
    with pytest.raises(ValidationError, match="OIDC"):
        Settings(
            environment="production",
            oidc_audience="",
            oidc_jwks_url="",
            vault_address="http://vault.internal:8200",
        )

    settings = Settings(
        environment="production",
        keycloak_issuer="https://identity.example/realms/reclaim",
        oidc_audience="reclaim-api",
        oidc_jwks_url="https://identity.example/realms/reclaim/protocol/openid-connect/certs",
        vault_address="https://vault.internal:8200",
        redpanda_security_protocol="SASL_SSL",
        redpanda_sasl_mechanism="SCRAM-SHA-512",
        redpanda_sasl_username="relay-principal",
        redpanda_sasl_password="test-only-password",
        redpanda_tls_ca_file="/run/secrets/redpanda-ca.pem",
        redpanda_tls_cert_file="/run/secrets/redpanda-client.pem",
        redpanda_tls_key_file="/run/secrets/redpanda-client-key.pem",
    )
    assert settings.oidc_algorithms == ("RS256",)
    invalid = settings.model_dump()
    invalid["keycloak_issuer"] = "http://identity.example/realms/reclaim"
    with pytest.raises(ValidationError, match="Keycloak"):
        Settings(**invalid)
    assert settings.vault_address.startswith("https://")


def test_local_settings_keep_replay_and_plaintext_broker_defaults() -> None:
    settings = Settings(environment="test")
    assert settings.run_mode == "replay"
    assert settings.live_actions_enabled is False
    assert settings.redpanda_security_protocol == "PLAINTEXT"


def test_default_redpanda_producer_kwargs_use_configured_security() -> None:
    settings = Settings(
        redpanda_brokers="broker.internal:9093",
        redpanda_security_protocol="SASL_SSL",
        redpanda_sasl_mechanism="SCRAM-SHA-512",
        redpanda_sasl_username="relay-principal",
        redpanda_sasl_password="test-only-password",
        redpanda_tls_ca_file="/tmp/ca.pem",
        redpanda_tls_cert_file="/tmp/client.pem",
        redpanda_tls_key_file="/tmp/client-key.pem",
    )
    kwargs = _default_producer_kwargs(settings)
    assert kwargs == {
        "bootstrap_servers": "broker.internal:9093",
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "SCRAM-SHA-512",
        "sasl_plain_username": "relay-principal",
        "sasl_plain_password": "test-only-password",
        "ssl_cafile": "/tmp/ca.pem",
        "ssl_certfile": "/tmp/client.pem",
        "ssl_keyfile": "/tmp/client-key.pem",
    }


def test_keycloak_realm_is_safe_for_production_service_identity_provisioning() -> None:
    realm = json.loads(
        (INFRA / "keycloak/realm-reclaim.json").read_text(encoding="utf-8")
    )
    assert realm["sslRequired"] == "all"
    assert realm["registrationAllowed"] is False
    assert realm["clients"]
    for client in realm["clients"]:
        assert client["directAccessGrantsEnabled"] is False
        assert client["publicClient"] is False
        if client["clientId"] == "reclaim-api":
            assert client["bearerOnly"] is True
        else:
            assert client["serviceAccountsEnabled"] is True
    assert all(
        "password" not in json.dumps(client).lower() for client in realm["clients"]
    )


def test_vault_policies_are_read_only_and_deny_secret_listing() -> None:
    for path in (INFRA / "vault/policies").glob("*.hcl"):
        content = path.read_text(encoding="utf-8")
        assert 'capabilities = ["create"' not in content
        assert 'capabilities = ["update"' not in content
        assert 'capabilities = ["delete"' not in content
        assert 'path "secret/metadata/' not in content or '"list"' not in content
    action = (INFRA / "vault/policies/action-gateway.hcl").read_text(encoding="utf-8")
    assert 'path "secret/data/tenants/+/connectors/+/action"' in action
    assert 'capabilities = ["read"]' in action


def test_vault_client_can_require_tls_for_production_secret_reads() -> None:
    with pytest.raises(SecretAccessDenied, match="HTTPS"):
        VaultSecretStore.from_address(
            "http://vault.internal:8200",
            token="test-only-token",
            service_identity="action-gateway",
            require_tls=True,
        )


def test_production_redpanda_policy_requires_tls_sasl_acl_and_principal_binding() -> (
    None
):
    policy = yaml.safe_load(
        (INFRA / "redpanda/production-security.yaml").read_text(encoding="utf-8")
    )
    assert policy["transport"] == {
        "tls": {"enabled": True, "client_auth": "required"},
        "sasl": {"enabled": True, "mechanisms": ["SCRAM-SHA-512"]},
        "acl": {"enabled": True, "default": "deny"},
    }
    assert policy["principal_binding"]["mode"] == "certificate-and-sasl-identity"
    assert policy["principal_binding"]["require_authenticated_principal"] is True
    assert policy["principals"]["reclaim-event-relay"]["allow"] == [
        {"operation": "write", "topic": "reclaim.domain.v1"}
    ]
    assert policy["principals"]["reclaim-n8n-orchestrator"]["allow"] == [
        {"operation": "read", "topic": "reclaim.domain.v1"}
    ]


def test_broker_capable_service_accounts_bind_to_declared_principals() -> None:
    accounts = yaml.safe_load(
        (INFRA / "security/service-accounts.yml").read_text(encoding="utf-8")
    )
    assert (
        accounts["services"]["event-relay"]["broker_principal"] == "reclaim-event-relay"
    )
    assert (
        accounts["services"]["n8n-main"]["broker_principal"]
        == "reclaim-n8n-orchestrator"
    )
    assert accounts["services"]["n8n-worker"]["broker_principal"] is None


def test_production_compose_mounts_broker_policy_and_secret_material_read_only() -> (
    None
):
    compose = yaml.safe_load(
        (INFRA / "docker-compose.production.yml").read_text(encoding="utf-8")
    )
    redpanda = compose["services"]["redpanda"]
    assert redpanda["profiles"] == ["production"]
    assert any("production-security.yaml" in volume for volume in redpanda["volumes"])
    assert all(
        ":ro" in volume
        for volume in redpanda["volumes"]
        if "redpanda-data" not in volume
    )
    command = " ".join(redpanda["command"])
    assert "--set redpanda.enable_sasl=true" in command
    assert "--set redpanda.kafka_enable_authorization=true" in command
    assert "--set redpanda.kafka_api[0].authentication_method=sasl" in command
    assert "--set redpanda.kafka_api[0].tls.require_client_auth=true" in command
    assert (
        "RECLAIM_REDPANDA_SECURITY_PROTOCOL"
        in compose["services"]["api"]["environment"]
    )
    assert (
        compose["services"]["api"]["environment"][
            "RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED"
        ]
        == "false"
    )
    assert (
        "RECLAIM_REDPANDA_SASL_PASSWORD"
        not in compose["services"]["api"]["environment"]
    )
    assert (
        compose["services"]["api"]["environment"]["RECLAIM_REDPANDA_SASL_PASSWORD_FILE"]
        == "/run/secrets/redpanda-sasl-password"
    )
    assert compose["services"]["api"]["environment"][
        "RECLAIM_KEYCLOAK_ISSUER"
    ].startswith("https://")


def test_production_compose_disables_dev_identity_and_uses_tls_for_control_planes() -> (
    None
):
    compose = yaml.safe_load(
        (INFRA / "docker-compose.production.yml").read_text(encoding="utf-8")
    )
    keycloak = compose["services"]["keycloak"]
    assert keycloak["profiles"] == ["production"]
    assert keycloak["command"][:2] == ["start", "--optimized"]
    assert keycloak["environment"]["KC_HTTP_ENABLED"] == "false"
    assert "KC_BOOTSTRAP_ADMIN_PASSWORD" not in keycloak["environment"]
    vault = compose["services"]["vault"]
    assert vault["profiles"] == ["production"]
    assert "-dev" not in " ".join(vault["command"])
    assert "VAULT_DEV_ROOT_TOKEN_ID" not in vault["environment"]
    n8n = compose["services"]["n8n-main"]
    assert n8n["profiles"] == ["production"]
    assert n8n["environment"]["N8N_SECURE_COOKIE"] == "true"
    assert "N8N_ENCRYPTION_KEY" in n8n["environment"]
    assert "RECLAIM_N8N_SERVICE_TOKEN" in n8n["environment"]
    assert (
        ":?RECLAIM_N8N_SERVICE_TOKEN is required"
        in n8n["environment"]["RECLAIM_N8N_SERVICE_TOKEN"]
    )


def test_n8n_rotation_is_explicitly_versioned_and_reconciles_references() -> None:
    script = (INFRA / "n8n/bootstrap.ps1").read_text(encoding="utf-8")
    assert "[switch]$Rotate" in script
    assert "RECLAIM_N8N_CREDENTIAL_REVISION" in script
    assert "Assert-WorkflowCredentialReference" in script
    assert "reclaim-orchestrator-service.$CredentialRevision" in script
    assert "reclaim-redpanda-readonly.$CredentialRevision" in script
