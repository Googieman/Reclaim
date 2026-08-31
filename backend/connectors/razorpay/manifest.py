"""Configuration declarations for the Razorpay Test Mode webhook connector.

The manifest is deliberately a declaration, not a provider client.  It names the
tenant-scoped verification reference and exact headers used by the adapter while
keeping live/replay labeling explicit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.secrets.vault import vault_webhook_secret_path
from packages.contracts.intake import RazorpayWebhookRequest

RAZORPAY_TEST_CONNECTOR_ID = "razorpay-test"
RAZORPAY_TEST_PROVIDER = "razorpay"
RAZORPAY_TEST_CONTRACT_VERSION = "2.0.0"
RAZORPAY_CORRELATION_SCHEMA_VERSION = "1.0.0"


class RazorpayRunMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class RazorpayHeaderConfiguration:
    """Exact inbound header names; values remain untrusted request data."""

    signature: str = "X-Razorpay-Signature"
    provider_event_id: str = "X-Razorpay-Event-Id"

    def __post_init__(self) -> None:
        if not self.signature.strip() or not self.provider_event_id.strip():
            raise ValueError("Razorpay webhook header names are required")
        if self.signature.lower() == self.provider_event_id.lower():
            raise ValueError("Razorpay webhook headers must identify different fields")


@dataclass(frozen=True, slots=True)
class RazorpayTestModeManifest:
    """Tenant-bound Test Mode declaration consumed by the webhook adapter."""

    tenant_id: str
    connector_id: str = RAZORPAY_TEST_CONNECTOR_ID
    contract_version: str = RAZORPAY_TEST_CONTRACT_VERSION
    provider: str = RAZORPAY_TEST_PROVIDER
    provider_mode: str = "test"
    run_mode: RazorpayRunMode = RazorpayRunMode.REPLAY
    credential_scope_ref: str = ""
    headers: RazorpayHeaderConfiguration = RazorpayHeaderConfiguration()
    signature_algorithm: str = "HMAC-SHA256"
    signature_encoding: str = "hex"
    required_fields: tuple[str, ...] = (
        "provider_event_id",
        "event_type",
        "event_timestamp",
        "verified_provider_correlation",
    )
    secret_rotation: str = "current-and-previous-versioned-secret"

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError("Razorpay manifest requires tenant scope")
        if self.connector_id != RAZORPAY_TEST_CONNECTOR_ID:
            raise ValueError("only the Razorpay Test Mode connector is supported")
        if self.provider_mode != "test":
            raise ValueError("Razorpay live provider mode is outside FS-001")
        if self.signature_algorithm != "HMAC-SHA256" or self.signature_encoding != "hex":
            raise ValueError("Razorpay Test Mode requires hexadecimal HMAC-SHA256")
        if not self.required_fields or len(set(self.required_fields)) != len(self.required_fields):
            raise ValueError("required webhook fields must be unique")
        expected_ref = vault_webhook_secret_path(self.tenant_id, self.connector_id)
        if self.credential_scope_ref and self.credential_scope_ref != expected_ref:
            raise ValueError("Razorpay credential reference is not tenant scoped")
        object.__setattr__(self, "credential_scope_ref", expected_ref)

    @property
    def label(self) -> str:
        """A replay label must remain visible in fixture and audit metadata."""

        return self.run_mode.value


def build_razorpay_test_mode_manifest(
    tenant_id: str,
    *,
    run_mode: RazorpayRunMode = RazorpayRunMode.REPLAY,
    headers: RazorpayHeaderConfiguration | None = None,
) -> RazorpayTestModeManifest:
    return RazorpayTestModeManifest(
        tenant_id=tenant_id,
        run_mode=run_mode,
        headers=headers or RazorpayHeaderConfiguration(),
    )


def validate_razorpay_manifest(manifest: RazorpayTestModeManifest) -> RazorpayTestModeManifest:
    """Validate the fixed Test Mode declaration before provider behavior is claimed."""

    if manifest.provider != RAZORPAY_TEST_PROVIDER:
        raise ValueError("Razorpay manifest provider is invalid")
    if manifest.credential_scope_ref != vault_webhook_secret_path(
        manifest.tenant_id, manifest.connector_id
    ):
        raise ValueError("Razorpay manifest secret reference is not tenant scoped")
    return manifest


class RazorpayFixtureLoader:
    """Load checked-in, labeled replay fixtures without loading secret material."""

    def __init__(self, fixture_directory: str | Path) -> None:
        self.fixture_directory = Path(fixture_directory)

    def load(self, fixture_name: str) -> dict[str, Any]:
        if not fixture_name or Path(fixture_name).name != fixture_name:
            raise ValueError("fixture name must be a single file name")
        path = self.fixture_directory / fixture_name
        if path.suffix.lower() != ".json":
            raise ValueError("Razorpay fixtures must be JSON")
        import json

        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Razorpay fixture could not be loaded") from exc
        if not isinstance(value, dict):
            raise ValueError("Razorpay fixture must contain a JSON object")
        if value.get("mode") != RazorpayRunMode.REPLAY.value:
            raise ValueError("checked-in Razorpay fixtures must be labeled replay")
        if "secret" in value or "signature_secret" in value:
            raise ValueError("Razorpay fixtures must not contain secret material")
        return value

    def load_webhook_request(
        self, fixture_name: str, *, verification_secret: str
    ) -> RazorpayWebhookRequest:
        """Render one replay fixture into the same request contract as live input."""

        fixture = self.load(fixture_name)
        if fixture.get("contract_version", "2.0.0") != "2.0.0":
            raise ValueError("Razorpay webhook fixture must use contract version 2.0.0")
        payload_value = fixture.get("original_payload")
        if not isinstance(payload_value, dict):
            raise ValueError("Razorpay webhook fixture payload must be an object")
        payload = json.dumps(payload_value, separators=(",", ":")).encode("utf-8")
        supplied_signature = fixture.get("signature")
        if not isinstance(supplied_signature, str):
            raise ValueError("Razorpay webhook fixture signature is required")
        signature = supplied_signature
        if supplied_signature == "fixture-signature-supplied-by-test":
            signature = hmac.new(
                verification_secret.encode("utf-8"), payload, hashlib.sha256
            ).hexdigest()
        return RazorpayWebhookRequest(
            tenant_id=str(fixture["tenant_id"]),
            correlation_id=str(fixture["correlation_id"]),
            connector_id=str(fixture["connector_id"]),
            original_payload=payload,
            payload_checksum=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            signature=signature,
            provider_event_id=str(fixture["provider_event_id"]),
            event_type=str(fixture["event_type"]),
            event_timestamp=_fixture_datetime(fixture["event_timestamp"]),
            received_at=_fixture_datetime(fixture["received_at"]),
        )


def _fixture_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Razorpay webhook fixture timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Razorpay webhook fixture timestamp is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Razorpay webhook fixture timestamp requires timezone")
    return parsed


def validate_secret_rotation_references(
    *,
    tenant_id: str,
    connector_id: str,
    current_reference: str,
    previous_reference: str | None = None,
) -> tuple[str, str | None]:
    """Validation seam for external secret-rotation control, without reading secrets."""

    expected = vault_webhook_secret_path(tenant_id, connector_id)
    if current_reference != expected:
        raise ValueError("current Razorpay secret reference is not tenant scoped")
    if previous_reference is not None and previous_reference != expected:
        raise ValueError("previous Razorpay secret reference is not tenant scoped")
    return current_reference, previous_reference


RAZORPAY_TEST_MODE_MANIFEST = build_razorpay_test_mode_manifest("demo-tenant")
