"""Client cache and rotation behavior for broker-delivered credentials."""

from __future__ import annotations

from pydantic import SecretStr

from secret_broker.contracts import SecretBundle, SecretRequest
from secret_broker.runtime_loader import RuntimeSecretLoader
from secret_broker.broker_client import SecretBrokerClient


def test_client_expiry_requests_new_version_without_serializing_values() -> None:
    now = [100.0]
    responses = [
        SecretBundle(
            secret_id="api.evidence",
            version=1,
            cache_ttl_seconds=5,
            values={"access_key_id": SecretStr("canary-one")},
        ),
        SecretBundle(
            secret_id="api.evidence",
            version=2,
            cache_ttl_seconds=5,
            values={"access_key_id": SecretStr("canary-two")},
        ),
    ]
    calls: list[SecretRequest] = []

    def transport(request: SecretRequest) -> SecretBundle:
        calls.append(request)
        return responses.pop(0)

    client = SecretBrokerClient(transport, clock=lambda: now[0])
    first = client.resolve(
        SecretRequest(secret_id="api.evidence", tenant_id="tenant-a")
    )
    cached = client.resolve(
        SecretRequest(secret_id="api.evidence", tenant_id="tenant-a")
    )
    now[0] += 5
    rotated = client.resolve(
        SecretRequest(secret_id="api.evidence", tenant_id="tenant-a")
    )

    assert first.version == cached.version == 1
    assert rotated.version == 2
    assert len(calls) == 2
    assert "canary-one" not in repr(client)
    assert RuntimeSecretLoader().environment(
        rotated, {"access_key_id": "RECLAIM_EVIDENCE_KEY"}
    ) == {"RECLAIM_EVIDENCE_KEY": "canary-two"}
