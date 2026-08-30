"""Implementation tests for the configured Razorpay Test Mode declaration."""

from pathlib import Path

import pytest
from connectors.razorpay.manifest import (
    RAZORPAY_TEST_CONNECTOR_ID,
    RazorpayFixtureLoader,
    RazorpayRunMode,
    build_razorpay_test_mode_manifest,
    validate_razorpay_manifest,
    validate_secret_rotation_references,
)


def test_manifest_is_test_mode_tenant_bound_and_replay_labeled() -> None:
    manifest = validate_razorpay_manifest(build_razorpay_test_mode_manifest("tenant-a"))

    assert manifest.connector_id == RAZORPAY_TEST_CONNECTOR_ID
    assert manifest.provider_mode == "test"
    assert manifest.run_mode is RazorpayRunMode.REPLAY
    assert manifest.label == "replay"
    assert manifest.credential_scope_ref.endswith(
        "/tenant-a/connectors/razorpay-test/webhook"
    )
    assert manifest.headers.signature == "X-Razorpay-Signature"


def test_manifest_rejects_provider_live_mode_and_cross_tenant_secret_reference() -> (
    None
):
    with pytest.raises(ValueError, match="provider mode"):
        build_razorpay_test_mode_manifest("tenant-a").__class__(
            tenant_id="tenant-a", provider_mode="live"
        )
    with pytest.raises(ValueError, match="not tenant scoped"):
        validate_secret_rotation_references(
            tenant_id="tenant-a",
            connector_id=RAZORPAY_TEST_CONNECTOR_ID,
            current_reference="secret/data/tenants/tenant-b/connectors/razorpay-test/webhook",
        )


def test_checked_in_fixtures_are_replay_labeled_and_secret_free() -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "razorpay"
    loader = RazorpayFixtureLoader(fixture_dir)

    fixture = loader.load("valid-payment-captured.json")

    assert fixture["mode"] == "replay"
    assert fixture["connector_id"] == RAZORPAY_TEST_CONNECTOR_ID
    assert "secret" not in fixture
