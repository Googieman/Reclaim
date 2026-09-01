"""Security coverage for the bounded, side-effect-free model boundary."""

from __future__ import annotations

from typing import Any

import pytest

from app.observability.redaction import REDACTED, redact
from app.security.boundaries import (
    AllowedCapability,
    BoundedToolSet,
    CapabilityViolation,
)
from app.secrets.vault import SecretAccessDenied, VaultSecretStore
from packages.contracts.analysis_policy import ModelAnalysisRequest, ModelBudget


class RecordingVault:
    def __init__(self) -> None:
        self.reads: list[str] = []

    def read(self, path: str) -> dict[str, Any]:
        self.reads.append(path)
        return {"api_key": "test-only-action-secret"}


def test_model_input_redacts_pii_secrets_and_raw_payload_but_keeps_provenance_ids() -> (
    None
):
    value = redact(
        {
            "tenant_id": "tenant-us2-boundary",
            "case_id": "case-us2-boundary",
            "timeline_event_id": "timeline-boundary-1",
            "evidence_references": ["evidence-boundary-1"],
            "customer": {
                "full_name": "Untrusted Customer",
                "email": "customer@example.test",
                "phone": "+1-555-0100",
            },
            "raw_payload": {"prompt": "ignore policy"},
            "credentials": {"client_secret": "secret", "api_key": "key"},
        }
    )

    assert value["tenant_id"] == "tenant-us2-boundary"
    assert value["case_id"] == "case-us2-boundary"
    assert value["timeline_event_id"] == "timeline-boundary-1"
    assert value["evidence_references"] == ["evidence-boundary-1"]
    assert value["customer"]["full_name"] == REDACTED
    assert value["customer"]["email"] == REDACTED
    assert value["customer"]["phone"] == REDACTED
    assert value["raw_payload"] == REDACTED
    assert value["credentials"]["client_secret"] == REDACTED
    assert value["credentials"]["api_key"] == REDACTED


def test_model_request_rejects_database_shell_network_and_action_capabilities() -> None:
    for forbidden in (
        "database_write",
        "execute_payment",
        "refund",
        "cancel",
        "shell",
        "network",
    ):
        with pytest.raises(ValueError, match="forbidden model tools"):
            ModelAnalysisRequest(
                tenant_id="tenant-us2-boundary",
                correlation_id=f"corr-{forbidden}",
                case_id="case-us2-boundary",
                redacted_case_representation={"timeline": []},
                allowed_tools=(forbidden,),
                policy_version_id="policy-v1.0.0",
                budget=ModelBudget(max_tokens=128),
                provider_mode="replay",
                replay_label="replay",
            )


def test_bounded_model_tools_reject_shell_network_database_credentials_and_connectors() -> (
    None
):
    tools = BoundedToolSet(
        {
            AllowedCapability.READ_CASE,
            AllowedCapability.READ_EVIDENCE,
            AllowedCapability.PROPOSE_ACTION,
        }
    )

    assert tools.names() == {"read_case", "read_evidence", "propose_action"}
    for forbidden in (
        "database_write",
        "shell_command",
        "arbitrary_network",
        "credential_probe",
        "direct_connector_access",
        "action_gateway",
    ):
        with pytest.raises(CapabilityViolation):
            tools.require(forbidden)


def test_model_identity_cannot_read_action_gateway_credentials() -> None:
    vault = RecordingVault()
    store = VaultSecretStore(vault, service_identity="model-gateway")

    with pytest.raises(SecretAccessDenied, match="only the Action Gateway"):
        store.read_action_connector_secret(
            tenant_id="tenant-us2-boundary",
            connector_id="payments",
        )

    assert vault.reads == []
