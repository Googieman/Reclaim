"""T109 Docker Compose topology and safe-default smoke boundary."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    REPOSITORY_ROOT / "infra" / "docker-compose.yml",
    REPOSITORY_ROOT / "infra" / "docker-compose.test.yml",
    REPOSITORY_ROOT / "infra" / "networks.yml",
)
SERVICES = (
    "web",
    "api",
    "event-relay",
    "workflow-worker",
    "model-gateway",
    "attribution",
    "evidence-connectors",
    "action-gateway",
    "postgres",
    "temporal",
    "redpanda",
    "neo4j",
    "minio",
    "redis",
    "n8n-main",
    "n8n-worker",
    "keycloak",
    "vault",
    "otel-collector",
    "prometheus",
    "grafana",
    "loki",
    "langfuse",
    "mlflow",
)


def test_compose_topology_has_all_services_and_safe_defaults() -> None:
    missing_files = [
        str(path.relative_to(REPOSITORY_ROOT))
        for path in COMPOSE_FILES
        if not path.exists()
    ]
    assert not missing_files, f"missing Compose artifacts: {missing_files}"

    compose = "\n".join(
        path.read_text(encoding="utf-8") for path in COMPOSE_FILES
    ).lower()
    normalized = re.sub(r"[-_]", "", compose)
    missing_services = [
        service for service in SERVICES if service.replace("-", "") not in normalized
    ]
    assert not missing_services, f"missing Compose services: {missing_services}"
    assert "internal: true" in compose
    assert "live_action_enabled" in compose and "false" in compose
    assert "provider_unavailability" in compose or "provider-unavailability" in compose
    assert "replay" in compose


def test_event_relay_topology_stays_on_data_services_with_no_extra_credentials() -> None:
    compose = yaml.safe_load(
        (REPOSITORY_ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    relay = compose["services"]["event-relay"]

    assert relay["networks"] == ["data-services"]
    assert set(relay["environment"]) == {
        "RECLAIM_TENANT_ID",
        "RECLAIM_DATABASE_URL",
        "RECLAIM_REDPANDA_BROKERS",
    }
    assert relay["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert relay["depends_on"]["redpanda"]["condition"] == "service_healthy"
