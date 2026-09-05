"""Static and command-construction contracts for T153 recovery faults."""

from __future__ import annotations

from pathlib import Path

import pytest

from support.t153_runtime import T153Config, compose_service_command


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "tests" / "support" / "t153_runtime.py"
RECOVERY = ROOT / "tests" / "acceptance" / "test_t153_restart_recovery.py"


def _config(project_name: str = "reclaim-t153-unit") -> T153Config:
    return T153Config(
        api_base_url="http://127.0.0.1:18000",
        web_base_url="http://127.0.0.1:13000",
        database_url="postgresql://reclaim:test@127.0.0.1:15432/reclaim",
        redpanda_brokers="127.0.0.1:19092",
        minio_endpoint="http://127.0.0.1:19000",
        project_name=project_name,
    )


@pytest.mark.parametrize("service", ("n8n-worker", "api", "redis"))
def test_t153_recovery_command_is_project_and_service_scoped(service: str) -> None:
    command = compose_service_command(_config(), service, "restart")

    assert command[:2] == ["docker", "compose"]
    assert command[2:4] == ["-p", "reclaim-t153-unit"]
    assert "-f" in command
    assert command[-2:] == ["restart", service]
    assert not {"down", "rm", "--volumes", "-v"}.intersection(command)


@pytest.mark.parametrize(
    ("project_name", "service", "action"),
    (
        ("reclaim-demo", "api", "restart"),
        ("reclaim-t153-unit", "postgres", "restart"),
        ("reclaim-t153-unit", "api", "down"),
    ),
)
def test_t153_recovery_command_rejects_unsafe_scope(
    project_name: str, service: str, action: str
) -> None:
    with pytest.raises(ValueError):
        compose_service_command(_config(project_name), service, action)


def test_t153_recovery_artifacts_capture_authority_and_redis_reload() -> None:
    combined = f"{RUNTIME.read_text(encoding='utf-8')}\n{RECOVERY.read_text(encoding='utf-8')}"
    for marker in (
        "redis_queue_state",
        "aof_last_load_status",
        "record_recovery_observation",
        "postgres_snapshot",
        "verify_minio_raw_report",
        '"n8n-worker"',
        '"api"',
        '"redis"',
    ):
        assert marker in combined
