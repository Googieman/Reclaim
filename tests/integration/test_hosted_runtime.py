"""Production-shaped runtime assembly tests."""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.runtime import HostedRuntime, build_hosted_runtime
from api.main import create_hosted_app


class Connection:
    def execute(self, sql: str, params: object | None = None) -> Any:
        del params
        assert sql == "SELECT 1"
        return self

    def fetchone(self) -> tuple[int]:
        return (1,)

    def close(self) -> None:
        return None


def production_settings() -> Settings:
    return Settings(
        environment="production",
        run_mode="live",
        replay_label="live",
        oidc_jwks_url="https://identity.example/.well-known/jwks.json",
        keycloak_issuer="https://identity.example/realms/reclaim",
        vault_address="https://vault.example:8200",
        redpanda_security_protocol="SASL_SSL",
        redpanda_sasl_username="relay",
        redpanda_sasl_password="provided-at-runtime",
        redpanda_tls_ca_file="/etc/secrets/ca.pem",
        redpanda_tls_cert_file="/etc/secrets/client.pem",
        redpanda_tls_key_file="/etc/secrets/client-key.pem",
    )


def test_hosted_runtime_assembles_authoritative_services_without_replay() -> None:
    runtime = build_hosted_runtime(
        production_settings(),
        connection_factory=Connection,
        oidc_verifier=object(),
    )

    assert isinstance(runtime, HostedRuntime)
    assert runtime.settings.demo_read_only_enabled is False
    assert runtime.settings.authoritative_demo_enabled is False
    assert runtime.intake_service is not None
    assert runtime.case_inbox_service is not None
    assert runtime.orchestration_service is not None


def test_hosted_readiness_uses_database_probe_not_replay() -> None:
    calls: list[str] = []

    class RecordingConnection(Connection):
        def execute(self, sql: str, params: object | None = None) -> Any:
            calls.append(sql)
            return super().execute(sql, params)

    runtime = build_hosted_runtime(
        production_settings(),
        connection_factory=RecordingConnection,
        oidc_verifier=object(),
    )

    runtime.check_readiness()

    assert calls == ["SELECT 1"]


def test_hosted_app_mounts_db_readiness_without_demo_routes() -> None:
    from fastapi.testclient import TestClient

    runtime = build_hosted_runtime(
        production_settings(),
        connection_factory=Connection,
        oidc_verifier=object(),
    )

    application = create_hosted_app(runtime=runtime)
    paths = {route.path for route in application.routes}
    assert "/demo/mode" not in paths
    assert TestClient(application).get("/health/ready").status_code == 200
