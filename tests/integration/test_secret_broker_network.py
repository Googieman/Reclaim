"""Optional transport gate for the private broker."""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration
def test_live_secret_broker_network_gate_if_configured() -> None:
    endpoint = os.getenv("RECLAIM_SECRET_BROKER_URL")
    if not endpoint:
        pytest.skip("RECLAIM_SECRET_BROKER_URL is required for live mTLS validation")
    pytest.fail("live mTLS broker qualification requires operator-owned certificates")


def test_private_broker_artifacts_require_mtls_and_loopback_application() -> None:
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    envoy = (root / "infra" / "secret-broker" / "envoy.yaml").read_text(
        encoding="utf-8"
    )
    entrypoint = (root / "infra" / "secret-broker" / "entrypoint.sh").read_text(
        encoding="utf-8"
    )
    dockerfile = (root / "infra" / "secret-broker" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "require_client_certificate: true" in envoy
    assert "port_value: 8443" in envoy
    assert "port_value: 8081" in envoy
    assert "127.0.0.1" in (root / "backend" / "secret_broker" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "secret_broker.main api" in entrypoint
    assert "port=9001" in (root / "backend" / "secret_broker" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "wait -n" in entrypoint
    assert "COPY /secrets" not in dockerfile
    assert "EXPOSE 8443" not in dockerfile
