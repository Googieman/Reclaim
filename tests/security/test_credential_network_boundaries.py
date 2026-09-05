"""Static credential and egress boundary checks for the Compose deployment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"


def _yaml(name: str) -> dict[str, Any]:
    value = yaml.safe_load((INFRA / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_service_credential_matrix_grants_action_credentials_only_to_gateway() -> None:
    document = _yaml("security/service-accounts.yml")
    services = document["services"]
    assert isinstance(services, dict)
    action_holders = [
        name
        for name, value in services.items()
        if value.get("action_connector_credentials") is True
    ]
    assert action_holders == ["action-gateway"]
    assert services["action-gateway"]["merchant_mutation"] is True
    assert all(
        value.get("merchant_mutation") is False
        for name, value in services.items()
        if name != "action-gateway"
    )
    action = document["action_credentials"]
    assert action["sole_principal"] == services["action-gateway"]["principal"]
    assert action["sole_principal"] not in action["forbidden_principals"]
    assert all(
        services[name]["principal"] in action["forbidden_principals"]
        for name in services
        if name != "action-gateway"
    )


def test_network_policy_is_explicit_default_deny_without_broad_egress() -> None:
    document = _yaml("security/network-policies.yml")
    enforcement = document["enforcement"]
    assert enforcement["default_deny_egress"] is True
    assert enforcement["unrestricted_egress"] is False
    services = document["services"]
    assert set(services) >= {
        "api",
        "workflow-worker",
        "model-gateway",
        "evidence-connectors",
        "action-gateway",
        "postgres",
        "redpanda",
        "neo4j",
        "minio",
        "redis",
        "keycloak",
        "vault",
    }
    allowed_symbols = {
        "api",
        "postgres",
        "temporal",
        "redpanda",
        "redis",
        "minio",
        "keycloak",
        "vault",
        "otel-collector",
        "prometheus",
        "loki",
        "langfuse",
        "mlflow",
        "model-provider-allowlist",
        "evidence-provider-allowlist",
        "merchant-controlled-action-allowlist",
        "workflow-worker",
        "model-gateway",
        "action-gateway",
    }
    for service, policy in services.items():
        assert isinstance(policy["egress"], list), service
        assert set(policy["egress"]).issubset(allowed_symbols), service
        serialized = repr(policy["egress"])
        assert "*" not in serialized
        assert "0.0.0.0/0" not in serialized
    assert services["model-gateway"]["egress"] == [
        "model-provider-allowlist",
        "otel-collector",
    ]
    assert (
        "merchant-controlled-action-allowlist" in services["action-gateway"]["egress"]
    )
    assert (
        "merchant-controlled-action-allowlist"
        not in services["model-gateway"]["egress"]
    )


def test_credential_audit_rules_are_redacted_references_only_and_honest_about_debt() -> (
    None
):
    document = _yaml("security/credential-audit.yml")
    rules = document["rules"]
    assert rules["repository_values"] == "forbidden"
    assert rules["repository_files"] == "references-only"
    assert rules["failure_mode"] == "deny-before-connector-call"
    assert document["observability"] == {
        "raw_evidence": False,
        "raw_prompts": False,
        "raw_outputs": False,
        "unnecessary_pii": False,
        "credentials_from_environment": False,
    }
    debt = " ".join(document["residual_deployment_debt"]).lower()
    assert "compose" in debt
    assert "mTLS".lower() in debt
    assert "sasl" in debt and "acl" in debt and "principal" in debt


def test_vault_policies_and_runtime_scope_match_the_credential_matrix() -> None:
    action_policy = (INFRA / "vault/policies/action-gateway.hcl").read_text(
        encoding="utf-8"
    )
    assert 'path "secret/data/tenants/+/connectors/+/action"' in action_policy
    assert 'capabilities = ["read"]' in action_policy
    for name in ("api.hcl", "model-gateway.hcl", "workflow-worker.hcl"):
        policy = (INFRA / "vault/policies" / name).read_text(encoding="utf-8")
        assert "/action" not in policy


def test_observability_configs_do_not_capture_raw_or_secret_material() -> None:
    for path in (INFRA / "langfuse/config.yaml", INFRA / "mlflow/config.yaml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        capture = document.get("capture", document.get("tracking", {}))
        assert capture.get("raw_evidence", False) is False
        assert capture.get("raw_prompts", False) is False
        assert capture.get("raw_outputs", False) is False
        assert capture.get("unnecessary_pii", False) is False
        assert document["export"]["credentials_from_environment"] is False


def test_policy_files_contain_no_literal_secret_values_or_broad_network_targets() -> (
    None
):
    for path in (
        INFRA / "security/network-policies.yml",
        INFRA / "security/service-accounts.yml",
        INFRA / "security/credential-audit.yml",
    ):
        text = path.read_text(encoding="utf-8").lower()
        assert "0.0.0.0/0" not in text
        assert "password:" not in text
        assert "api_key:" not in text
        assert "secret_value" not in text


@pytest.mark.parametrize(
    "service",
    (
        "web",
        "api",
        "workflow-worker",
        "model-gateway",
        "evidence-connectors",
        "replay",
        "evaluation",
    ),
)
def test_non_gateway_service_accounts_are_explicitly_non_mutating(service: str) -> None:
    document = _yaml("security/service-accounts.yml")
    value = document["services"][service]
    assert value["action_connector_credentials"] is False
    assert value["merchant_mutation"] is False
    assert value["principal"] != document["action_credentials"]["sole_principal"]
