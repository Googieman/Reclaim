"""Static deployment contract for the locally buildable product path."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _compose_short_volume_pairs(service: dict[str, object]) -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    for entry in service.get("volumes", []):
        if not isinstance(entry, str):
            continue
        source, target, *_rest = entry.split(":")
        pairs.append((source, target, entry))
    return pairs


def test_web_and_api_are_locally_buildable_and_health_checked() -> None:
    compose = yaml.safe_load(
        (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]

    for service_name, dockerfile in (
        ("web", "frontend/Dockerfile"),
        ("api", "backend/Dockerfile"),
    ):
        service = services[service_name]
        assert service["build"]["context"] == ".."
        assert service["build"]["dockerfile"] == dockerfile
        assert "healthcheck" in service
        assert (ROOT / dockerfile).is_file()

    api_dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    web_dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    versions = (ROOT / "infra" / "versions.env").read_text(encoding="utf-8")
    assert "aiokafka==0.12.0" in api_dockerfile
    assert "PyJWT==2.10.1" in api_dockerfile
    assert "minio==7.2.12" in api_dockerfile
    assert "prometheus-client==0.21.1" in api_dockerfile
    assert "node:22.14.0-alpine3.21" in web_dockerfile
    assert "NODE_VERSION=22.14.0" in versions


def test_railway_api_dockerfile_avoids_unsupported_buildkit_cache_mounts() -> None:
    api_dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "--mount=type=cache" not in api_dockerfile


def test_railway_api_dockerfile_uses_exec_form_healthcheck() -> None:
    api_dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "CMD-SHELL" not in api_dockerfile
    assert 'CMD ["python", "-c",' in api_dockerfile


def test_default_demo_is_low_ram_same_origin_and_authoritative_fresh() -> None:
    compose = yaml.safe_load(
        (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    web_environment = services["web"]["environment"]
    api_environment = services["api"]["environment"]

    assert web_environment["NEXT_PUBLIC_API_BASE_URL"] == ""
    assert web_environment["RECLAIM_API_INTERNAL_BASE_URL"] == "http://api:8000"
    assert web_environment["NEXT_PUBLIC_RUN_MODE"] == "live"
    assert api_environment["RECLAIM_DEMO_READ_ONLY_ENABLED"] == "false"
    assert api_environment["RECLAIM_AUTHORITATIVE_DEMO_ENABLED"] == "true"
    assert api_environment["RECLAIM_FRESH_AGENT_ENABLED"] == "true"
    assert api_environment["RECLAIM_RUN_MODE"] == "live"
    assert api_environment["RECLAIM_FRESH_AGENT_ACTION_ENVIRONMENT"] == "simulator"
    assert api_environment["RECLAIM_LIVE_ACTIONS_ENABLED"] == "false"
    assert api_environment["RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED"] == "false"

    assert "profiles" not in services["web"]
    assert "profiles" not in services["api"]
    assert "profiles" not in services["postgres"]
    for service_name in ("temporal", "redpanda", "neo4j", "keycloak", "vault"):
        assert "full" in services[service_name]["profiles"]


def test_postgres_bootstrap_mounts_migration_dispatcher_and_role_entries() -> None:
    compose = yaml.safe_load(
        (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    postgres = compose["services"]["postgres"]
    volumes = _compose_short_volume_pairs(postgres)

    assert all(target != "/docker-entrypoint-initdb.d" for _, target, _ in volumes)
    assert any(target == "/reclaim-migrations" for _, target, _ in volumes)
    assert any(
        source == "./postgres/010-apply-reclaim-migrations.sh"
        and target == "/docker-entrypoint-initdb.d/010-apply-reclaim-migrations.sh"
        for source, target, _ in volumes
    )
    assert any(
        source == "./postgres/900-n8n-role.sql"
        and target == "/docker-entrypoint-initdb.d/900-n8n-role.sql"
        for source, target, _ in volumes
    )
    assert any(
        source == "./postgres/901-n8n-role-password.sh"
        and target == "/docker-entrypoint-initdb.d/901-n8n-role-password.sh"
        for source, target, _ in volumes
    )


def test_api_and_web_use_host_port_variables_without_changing_container_ports() -> None:
    compose = yaml.safe_load(
        (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    web_ports = compose["services"]["web"]["ports"]
    api_ports = compose["services"]["api"]["ports"]

    assert any("${RECLAIM_WEB_PORT:-3000}" in port for port in web_ports)
    assert any("${RECLAIM_API_PORT:-8000}" in port for port in api_ports)
    assert any(port.endswith(":3000") for port in web_ports)
    assert any(port.endswith(":8000") for port in api_ports)


def test_windows_demo_helpers_exist_and_do_not_delete_data() -> None:
    start = (ROOT / "scripts" / "start-demo.ps1").read_text(encoding="utf-8").lower()
    status = (ROOT / "scripts" / "status-demo.ps1").read_text(encoding="utf-8").lower()
    stop = (ROOT / "scripts" / "stop-demo.ps1").read_text(encoding="utf-8").lower()

    for name in ("start-demo.ps1", "status-demo.ps1", "stop-demo.ps1"):
        assert (ROOT / "scripts" / name).is_file()

    assert "docker compose" in start
    assert "up -d --build --wait --wait-timeout 180 postgres redpanda redis minio api event-relay web n8n-main n8n-worker" in start
    assert "ps event-relay" in start

    assert "docker compose" in status
    assert "--profile full ps postgres redpanda redis minio api event-relay web n8n-main n8n-worker" in status

    assert "docker compose" in stop
    assert "stop n8n-worker n8n-main web event-relay api minio redis redpanda postgres" in stop

    for content in (start, status, stop):
        assert "down -v" not in content
        assert "volume rm" not in content
        assert "docker volume" not in content
        assert "remove-item" not in content


def test_event_relay_reuses_api_image_with_scoped_runtime_configuration() -> None:
    compose = yaml.safe_load(
        (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    api = services["api"]
    relay = services["event-relay"]

    assert relay["image"] == api["image"]
    assert relay["build"] == api["build"]
    assert relay["command"] == ["python", "-m", "app.events.outbox_relay"]
    assert relay["networks"] == ["data-services"]
    assert set(relay["environment"]) == {
        "RECLAIM_TENANT_ID",
        "RECLAIM_DATABASE_URL",
        "RECLAIM_REDPANDA_BROKERS",
    }
    assert "ports" not in relay
    assert "extra_hosts" not in relay
    assert relay["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert relay["depends_on"]["redpanda"]["condition"] == "service_healthy"


def test_replay_ui_has_no_consequential_control_path() -> None:
    page = (
        ROOT / "frontend" / "src" / "app" / "cases" / "[caseId]" / "page.tsx"
    ).read_text(encoding="utf-8")
    approval = (
        ROOT / "frontend" / "src" / "components" / "case" / "ApprovalPanel.tsx"
    ).read_text(encoding="utf-8")
    escalation = (
        ROOT / "frontend" / "src" / "components" / "case" / "EscalationPanel.tsx"
    ).read_text(encoding="utf-8")

    assert 'const readOnly = view.read_only || mode.final_mode !== "live"' in page
    assert "!readOnly &&" in approval
    assert "!readOnly &&" in escalation
    assert "REPLAY is read-only" in approval
    assert "REPLAY is read-only" in escalation
