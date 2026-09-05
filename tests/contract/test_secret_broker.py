"""Contract tests for the private secrets broker."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from secret_broker.contracts import SecretBundle, SecretRequest
from secret_broker.policy import IdentityGrant, SecretDefinition, SecretPolicy
from secret_broker.service import (
    SecretBrokerService,
    SecretForbidden,
    SecretUnavailable,
)


def policy() -> SecretPolicy:
    return SecretPolicy(
        identities=(
            IdentityGrant(
                identity="action-gateway",
                certificate_uri_san="spiffe://reclaim/final/action-gateway",
                tenants=frozenset({"tenant-a"}),
                secret_ids=frozenset({"razorpay.test.action"}),
            ),
            IdentityGrant(
                identity="intake-api",
                certificate_uri_san="spiffe://reclaim/final/intake-api",
                tenants=frozenset({"tenant-a"}),
                secret_ids=frozenset({"razorpay.test.webhook"}),
            ),
            IdentityGrant(
                identity="agent-runner",
                certificate_uri_san="spiffe://reclaim/final/agent-runner",
                tenants=frozenset(),
                secret_ids=frozenset(),
            ),
            IdentityGrant(
                identity="model-provider",
                certificate_uri_san="spiffe://reclaim/final/model-provider",
                tenants=frozenset(),
                secret_ids=frozenset({"model.provider"}),
            ),
        ),
        secrets=(
            SecretDefinition(
                secret_id="razorpay.test.action",
                scope="tenant",
                vault_path="secret/data/tenants/tenant-a/connectors/razorpay/action",
                cache_ttl_seconds=60,
                identities=frozenset({"action-gateway"}),
            ),
            SecretDefinition(
                secret_id="razorpay.test.webhook",
                scope="tenant",
                vault_path="secret/data/tenants/tenant-a/connectors/razorpay/webhook",
                cache_ttl_seconds=300,
                identities=frozenset({"intake-api"}),
            ),
            SecretDefinition(
                secret_id="model.provider",
                scope="service",
                vault_path="secret/data/reclaim/final/model/provider",
                cache_ttl_seconds=300,
                identities=frozenset({"model-provider"}),
            ),
        ),
    )


class Vault:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {"key_id": "test-key", "key_secret": "test-secret"}
        self.paths: list[str] = []

    def read(self, path: str) -> dict[str, str]:
        self.paths.append(path)
        return self.values


class Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, **event: object) -> None:
        self.events.append(event)


def test_contract_rejects_unknown_fields_and_masks_secret_values() -> None:
    with pytest.raises(ValidationError):
        SecretRequest(secret_id="model.provider", unexpected="reject")
    with pytest.raises(ValidationError):
        SecretRequest(secret_id="../vault")

    bundle = SecretBundle(
        secret_id="model.provider",
        version=1,
        cache_ttl_seconds=300,
        values={"api_key": SecretStr("canary-secret")},
    )
    assert "canary-secret" not in repr(bundle)
    assert bundle.to_delivery_dict()["values"]["api_key"] == "canary-secret"


def test_authorized_tenant_request_audits_before_release_and_uses_exact_path() -> None:
    vault = Vault()
    audit = Audit()
    service = SecretBrokerService(policy(), vault=vault, audit=audit)

    bundle = service.resolve(
        identity_uri="spiffe://reclaim/final/action-gateway",
        request=SecretRequest(secret_id="razorpay.test.action", tenant_id="tenant-a"),
        request_id="request-1",
    )

    assert bundle.values["key_id"].get_secret_value() == "test-key"
    assert vault.paths == ["secret/data/tenants/tenant-a/connectors/razorpay/action"]
    assert [event["event_kind"] for event in audit.events] == [
        "access_intent",
        "delivery",
    ]
    assert all("test-secret" not in repr(event) for event in audit.events)


def test_forbidden_identity_and_cross_tenant_are_uniform_denials() -> None:
    service = SecretBrokerService(policy(), vault=Vault(), audit=Audit())
    requests = (
        (
            "spiffe://reclaim/final/agent-runner",
            SecretRequest(secret_id="model.provider"),
        ),
        (
            "spiffe://reclaim/final/action-gateway",
            SecretRequest(secret_id="razorpay.test.action", tenant_id="tenant-b"),
        ),
        (
            "spiffe://reclaim/final/action-gateway",
            SecretRequest(secret_id="not-known", tenant_id="tenant-a"),
        ),
    )
    errors = []
    for identity_uri, request in requests:
        with pytest.raises(SecretForbidden) as caught:
            service.resolve(
                identity_uri=identity_uri, request=request, request_id="request-2"
            )
        errors.append(str(caught.value))
    assert errors[0] == errors[1] == errors[2] == "secret access forbidden"


def test_service_secret_rejects_tenant_and_cache_never_exceeds_declared_ttl() -> None:
    service = SecretBrokerService(policy(), vault=Vault(), audit=Audit())
    with pytest.raises(SecretForbidden, match="secret access forbidden"):
        service.resolve(
            identity_uri="spiffe://reclaim/final/model-provider",
            request=SecretRequest(secret_id="model.provider", tenant_id="tenant-a"),
            request_id="request-3",
        )

    with pytest.raises(ValueError, match="cache TTL"):
        SecretDefinition(
            secret_id="unsafe.secret",
            scope="tenant",
            vault_path="secret/data/unsafe",
            cache_ttl_seconds=301,
            identities=frozenset({"action-gateway"}),
        )


def test_vault_failure_is_unavailable_and_never_returns_partial_values() -> None:
    class BrokenVault(Vault):
        def read(self, path: str) -> dict[str, str]:
            raise RuntimeError("provider canary must not escape")

    service = SecretBrokerService(policy(), vault=BrokenVault(), audit=Audit())
    with pytest.raises(
        SecretUnavailable, match="secret temporarily unavailable"
    ) as caught:
        service.resolve(
            identity_uri="spiffe://reclaim/final/action-gateway",
            request=SecretRequest(
                secret_id="razorpay.test.action", tenant_id="tenant-a"
            ),
            request_id="request-4",
        )
    assert "provider canary" not in str(caught.value)
