"""Source contracts for the isolated T153 validation overlay and harness."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
import subprocess

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OVERLAY = REPOSITORY_ROOT / "infra" / "docker-compose.t153.yml"
HARNESS = REPOSITORY_ROOT / "scripts" / "validate-t153.ps1"
T153_SUPPORT = REPOSITORY_ROOT / "tests" / "support" / "t153_runtime.py"
T153_ACCEPTANCE = REPOSITORY_ROOT / "tests" / "acceptance" / "test_t153_n8n_runtime.py"

EXPECTED_SERVICES = {
    "postgres",
    "redpanda",
    "redis",
    "minio",
    "api",
    "web",
    "event-relay",
    "n8n-main",
    "n8n-worker",
}

EXPECTED_PORTS = {
    "web": ("RECLAIM_WEB_PORT", "13000", "3000"),
    "api": ("RECLAIM_API_PORT", "18000", "8000"),
    "postgres": ("RECLAIM_POSTGRES_PORT", "15432", "5432"),
    "minio": ("RECLAIM_MINIO_PORT", "19000", "9000"),
    "redpanda": (
        "RECLAIM_REDPANDA_PORT",
        "19092",
        "${RECLAIM_REDPANDA_PORT:-19092}",
    ),
    "n8n-main": ("RECLAIM_N8N_PORT", "15678", "5678"),
}


def _read_source(path: Path) -> str:
    assert path.exists(), f"missing required T153 artifact: {path.relative_to(REPOSITORY_ROOT)}"
    return path.read_text(encoding="utf-8")


class _ComposeLoader(yaml.SafeLoader):
    """Load Compose's merge tag without treating it as an unknown YAML tag."""


_ComposeLoader.add_constructor(
    "!override", lambda loader, node: loader.construct_sequence(node)
)


def _overlay() -> dict:
    return yaml.load(_read_source(OVERLAY), Loader=_ComposeLoader)


def _merged_compose_config() -> dict:
    environment = os.environ.copy()
    environment.update(
        {
            "COMPOSE_PROJECT_NAME": "reclaim-t153-task4-review",
            "RECLAIM_WEB_PORT": "23100",
            "RECLAIM_API_PORT": "28100",
            "RECLAIM_POSTGRES_PORT": "25432",
            "RECLAIM_MINIO_PORT": "29100",
            "RECLAIM_REDPANDA_PORT": "29192",
            "RECLAIM_N8N_PORT": "25178",
        }
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(REPOSITORY_ROOT / "infra" / "docker-compose.yml"),
            "-f",
            str(OVERLAY),
            "--profile",
            "t153",
            "config",
            "--format",
            "json",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _port_list(service: dict) -> list[dict]:
    ports = service.get("ports", [])
    return ports if isinstance(ports, list) else [ports]


def test_overlay_has_exact_t153_service_inventory_without_temporal() -> None:
    source = _read_source(OVERLAY).lower()
    services = _overlay()["services"]

    assert set(services) == EXPECTED_SERVICES
    assert "workflow-worker" not in source
    assert "temporal" not in source


def test_overlay_exposes_only_loopback_ports_with_unique_configurable_defaults() -> None:
    services = _overlay()["services"]
    default_ports: list[str] = []

    for service, (variable, default, container_port) in EXPECTED_PORTS.items():
        assert services[service]["ports"] == [
            f'127.0.0.1:${{{variable}:-{default}}}:{container_port}'
        ]
        default_ports.append(default)

    assert len(default_ports) == len(set(default_ports))
    assert "RECLAIM_WEB_BIND" not in _read_source(OVERLAY)
    assert "RECLAIM_API_BIND" not in _read_source(OVERLAY)


def test_merged_t153_config_replaces_base_ports_and_honors_overrides() -> None:
    config = _merged_compose_config()
    expected = {
        "web": ("23100", 3000),
        "api": ("28100", 8000),
        "postgres": ("25432", 5432),
        "minio": ("29100", 9000),
        "redpanda": ("29192", 29192),
        "n8n-main": ("25178", 5678),
    }

    for service_name, (published, target) in expected.items():
        ports = _port_list(config["services"][service_name])
        assert ports == [
            {
                "host_ip": "127.0.0.1",
                "mode": "ingress",
                "published": published,
                "protocol": "tcp",
                "target": target,
            }
        ]


def test_merged_t153_config_keeps_all_required_loopback_mappings() -> None:
    config = _merged_compose_config()

    assert {
        service_name
        for service_name, service in config["services"].items()
        if service.get("ports")
    } == {"web", "api", "postgres", "minio", "redpanda", "n8n-main"}

    for service_name in ("web", "api", "postgres", "minio", "redpanda", "n8n-main"):
        assert len(_port_list(config["services"][service_name])) == 1


def test_overlay_keeps_internal_broker_address_and_enables_redis_aof() -> None:
    source = _read_source(OVERLAY)
    redpanda_command = " ".join(_overlay()["services"]["redpanda"]["command"])

    assert "internal://redpanda:9092" in redpanda_command
    assert "external://127.0.0.1:${RECLAIM_REDPANDA_PORT:-19092}" in redpanda_command
    assert "redpanda:9092" in source
    redis_command = _overlay()["services"]["redis"]["command"]
    assert "--appendonly" in redis_command
    assert "yes" in redis_command


def test_t153_event_relay_disables_inherited_api_healthcheck() -> None:
    overlay = _read_source(OVERLAY)

    relay_start = overlay.index("  event-relay:")
    relay_source = overlay[relay_start:]
    assert "healthcheck:" in relay_source
    assert "disable: true" in relay_source


def test_t153_fresh_database_seeds_only_the_canonical_validation_tenant() -> None:
    overlay = _read_source(OVERLAY)
    seed_path = REPOSITORY_ROOT / "infra" / "postgres" / "902-t153-canonical-tenant.sql"
    seed = _read_source(seed_path)

    assert "902-t153-canonical-tenant.sql" in overlay
    assert "tenant-canonical-demo" in seed
    assert "ON CONFLICT (tenant_id) DO NOTHING" in seed
    assert "INSERT INTO public.tenants" in seed
    assert "tenant-canonical-demo" in seed


def test_t153_networks_use_explicit_configurable_non_default_subnets() -> None:
    overlay = _overlay()

    assert set(overlay["networks"]) == {
        "public-ingress",
        "app-services",
        "data-services",
        "observability",
        "t153-published",
    }
    for network_name in overlay["networks"]:
        network = overlay["networks"][network_name]
        assert network["ipam"]["config"]
        assert "RECLAIM_T153_" in network["ipam"]["config"][0]["subnet"]


def test_t153_published_network_is_limited_to_loopback_mapped_services() -> None:
    services = _overlay()["services"]

    assert services["postgres"]["networks"] == ["t153-published"]
    assert services["redpanda"]["networks"] == ["t153-published"]
    assert services["minio"]["networks"] == ["t153-published"]
    assert services["n8n-main"]["networks"] == ["t153-published"]


def test_n8n_main_uses_the_image_entrypoint_command() -> None:
    config = _merged_compose_config()

    assert config["services"]["n8n-main"]["command"] == ["start"]


def test_n8n_role_can_connect_but_cannot_use_the_application_schema() -> None:
    source = _read_source(REPOSITORY_ROOT / "infra" / "postgres" / "900-n8n-role.sql")

    assert "GRANT CONNECT ON DATABASE reclaim TO n8n" in source
    assert "GRANT CREATE ON DATABASE reclaim TO n8n" in source
    assert "REVOKE ALL ON SCHEMA public FROM n8n" in source


def test_overlay_builds_source_images_and_forces_all_action_flags_false() -> None:
    compose = _overlay()
    source = _read_source(OVERLAY)

    assert compose["services"]["api"]["build"]
    assert compose["services"]["web"]["build"]
    assert 'RECLAIM_LIVE_ACTIONS_ENABLED: "false"' in source
    assert 'RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED: "false"' in source
    assert re.search(r"RECLAIM_LIVE_ACTION_ENABLED\s*:\s*[\"']?false", source)


def test_harness_validates_safe_project_before_destructive_cleanup_and_preserves_failures() -> None:
    source = _read_source(HARNESS)

    assert re.search(r"\^reclaim-t153-\[a-z0-9-\]\+\$", source)
    assert "Assert-SafeProjectName" in source
    assert source.index("Assert-SafeProjectName") < source.index("down --volumes")
    assert "if ($Cleanup)" in source or "if ($Cleanup.IsPresent)" in source
    assert "down --volumes" in source
    assert "finally" not in source.lower() or "cleanup" in source.lower()
    assert "failure" in source.lower() or "preserv" in source.lower()


def test_harness_prepare_and_run_contracts_are_explicit() -> None:
    source = _read_source(HARNESS)

    for required in (
        "N8N_API_KEY",
        "N8N_KAFKA_CREDENTIAL_DATA_JSON",
        "RECLAIM_N8N_SERVICE_TOKEN",
    ):
        assert required in source


def test_run_fails_closed_when_task5_or_task7_artifacts_are_missing() -> None:
    source = _read_source(HARNESS)

    for required in (
        "tests/acceptance/test_t153_n8n_runtime.py",
        "tests/acceptance/test_t153_restart_recovery.py",
        "frontend/playwright.t153.config.ts",
        "frontend/src/components/cases/CaseInbox.live.browser.spec.ts",
        "frontend/src/app/cases/[caseId]/CaseDetail.live.browser.spec.ts",
        "Task 5 acceptance artifacts",
        "Task 7 live browser artifacts",
    ):
        assert required in source

    assert "skipped_missing_task5_tests" not in source
    assert "skipped_missing_task7_script" not in source
    assert re.search(r'throw\s+"Task 5 acceptance artifacts', source)
    assert re.search(r'throw\s+"Task 7 live browser artifacts', source)
    assert source.index('state = "run_complete"') > source.index("Invoke-RunGates")


def test_run_persists_in_progress_before_bootstrap_and_saves_then_rethrows() -> None:
    source = _read_source(HARNESS)
    run_start = source.index("function Run-T153")
    cleanup_start = source.index("function Cleanup-T153")
    run_source = source[run_start:cleanup_start]

    assert 'state = "in_progress"' in run_source
    assert "Save-ProjectRecord -Record $record" in run_source
    assert run_source.index("Save-ProjectRecord -Record $record") < run_source.index("$bootstrapPath")
    assert "Save-FailedProjectRecord" in run_source
    assert re.search(
        r"catch\s*\{.*Save-FailedProjectRecord.*throw",
        run_source,
        flags=re.DOTALL,
    )
    assert "gate_exit_evidence" in source


def test_harness_persists_sanitized_failure_and_gate_exit_evidence() -> None:
    source = _read_source(HARNESS)

    for required in (
        "Save-FailedProjectRecord",
        "failure.json",
        "gate_exit_evidence",
        "failed",
        "Preserving T153 project and volumes",
    ):
        assert required.lower() in source.lower()


def test_harness_redacts_compose_secrets_from_process_and_local_env_files() -> None:
    source = _read_source(HARNESS)

    for required in (
        ".env",
        "infra\\.env",
        "N8N_ENCRYPTION_KEY",
        "N8N_DB_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "RECLAIM_MINIO_ACCESS_KEY",
        "RECLAIM_MINIO_SECRET_KEY",
        "Get-Content",
    ):
        assert required in source
    assert "COMPOSE_ENV_FILES" not in source


def test_harness_keeps_minio_credentials_process_only_for_acceptance() -> None:
    source = _read_source(HARNESS)

    assert "publicGateSecretEnvironmentNames" in source
    assert '"RECLAIM_MINIO_ACCESS_KEY"' in source
    assert '"RECLAIM_MINIO_SECRET_KEY"' in source
    assert "secretEnvironmentNamesToClear" in source
    assert "publicGateSecretEnvironmentNames -notcontains $_" in source
    assert "Write-SanitizedArtifact" in source


def test_harness_redacts_custom_values_loaded_from_a_temporary_compose_env_file(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        raise AssertionError("pwsh is required for the PowerShell redaction contract")
    source = _read_source(HARNESS)

    script_root = tmp_path / "repository"
    script_directory = script_root / "scripts"
    infra_directory = script_root / "infra"
    script_directory.mkdir(parents=True)
    infra_directory.mkdir()
    shutil.copy2(HARNESS, script_directory / HARNESS.name)

    secrets = {
        "N8N_ENCRYPTION_KEY": "file-encryption-value-9f2c",
        "N8N_DB_PASSWORD": "file-db-password-value-7a1b",
        "MINIO_ROOT_PASSWORD": "file-minio-root-password-4c8d",
        "RECLAIM_MINIO_SECRET_KEY": "file-reclaim-minio-secret-6e0a",
    }
    (script_root / ".env").write_text(
        "\n".join(f"{name}={value}" for name, value in secrets.items()) + "\n",
        encoding="utf-8",
    )
    (infra_directory / ".env").write_text("# no secrets here\n", encoding="utf-8")

    script = (script_directory / HARNESS.name).as_posix()
    command = (
        f". '{script}' -DefineOnly; "
        "Redact-Text -Text $env:T153_TEST_TEXT"
    )
    environment = os.environ.copy()
    for name in secrets:
        environment.pop(name, None)
    environment["T153_TEST_TEXT"] = " | ".join(secrets.values())
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    sanitized_output = result.stdout + result.stderr
    for value in secrets.values():
        assert value not in sanitized_output
    assert sanitized_output.count("[REDACTED]") == len(secrets)

    for required in (
        "--build",
        "--wait",
        "COMPOSE_PROJECT_NAME",
        "docker volume inspect",
        "Get-Date -AsUTC",
        "awaiting_n8n_operator_setup",
        "bootstrap.ps1",
        "-Activate",
        "pytest",
        "test:browser:t153",
    ):
        assert required in source


def test_harness_records_sanitized_metadata_and_only_exports_public_endpoints() -> None:
    source = _read_source(HARNESS)

    for required in (
        "Docker Engine",
        "Docker Compose",
        "git commit",
        "dirty-path",
        "image",
        "[REDACTED]",
        "container health",
        "exit code",
        "RECLAIM_T153_API_BASE_URL",
        "RECLAIM_T153_WEB_BASE_URL",
        "RECLAIM_DATABASE_URL",
        "RECLAIM_REDPANDA_BROKERS",
        "RECLAIM_MINIO_ENDPOINT",
    ):
        assert required.lower() in source.lower()

    assert "raw narrative" in source.lower()
    assert "N8N_API_KEY" in source
    assert "RECLAIM_N8N_SERVICE_TOKEN" in source
    assert "N8N_KAFKA_CREDENTIAL_DATA_JSON" in source


def test_harness_cleanup_prints_exact_project_and_named_volumes() -> None:
    source = _read_source(HARNESS)

    assert "postgres-data" in source
    assert "redpanda-data" in source
    assert "redis-data" in source
    assert "minio-data" in source
    assert "Write-Host" in source
    assert "removed" in source.lower()


def test_t153_runtime_support_declares_explicit_authority_and_environment_contract() -> None:
    source = _read_source(T153_SUPPORT)

    for required in (
        "RECLAIM_T153_API_BASE_URL",
        "RECLAIM_T153_WEB_BASE_URL",
        "RECLAIM_DATABASE_URL",
        "RECLAIM_REDPANDA_BROKERS",
        "RECLAIM_MINIO_ENDPOINT",
        "RECLAIM_T153_PROJECT_NAME",
        "tenant-canonical-demo",
        "SET LOCAL reclaim.tenant_id = 'tenant-canonical-demo'",
        "reclaim.domain.v1",
        "serialize_event",
        "docker",
        "reclaim-demo",
    ):
        assert required in source


def test_t153_acceptance_contract_has_no_narrative_or_arbitrary_project_path() -> None:
    source = _read_source(T153_ACCEPTANCE)

    for required in (
        "demo-reviewer",
        "reported_amount_minor",
        "reported_currency",
        "awaiting_human",
        "requires_attention",
        "model_unavailable",
        "policy_failed",
        "raw_input_reference",
        "narrative",
        "reclaim-demo",
    ):
        assert required in source
    assert "print(" not in source
    assert "response.text" not in source


def test_harness_stops_at_operator_setup_without_marking_acceptance_complete() -> None:
    source = _read_source(HARNESS)
    run_start = source.index("function Run-T153")
    cleanup_start = source.index("function Cleanup-T153")
    run_source = source[run_start:cleanup_start]

    assert "awaiting_n8n_operator_setup" in run_source
    assert "N8N_API_KEY" in run_source
    assert "N8N_KAFKA_CREDENTIAL_DATA_JSON" in run_source
    assert "RECLAIM_N8N_SERVICE_TOKEN" in run_source
    assert "return" in run_source
    assert 'state = "run_complete"' in run_source


def test_harness_parses_raw_machine_json_before_sanitizing_evidence(
    tmp_path: Path,
) -> None:
    """Redaction must not corrupt JSON used for authoritative validation."""

    pwsh = shutil.which("pwsh")
    if pwsh is None:
        raise AssertionError("pwsh is required for the PowerShell volume-proof contract")

    script = HARNESS.as_posix().replace("'", "''")
    artifact = (tmp_path / "volume-proof.txt").as_posix().replace("'", "''")
    command = f"""
. '{script}' -DefineOnly

function Invoke-RecordedCommand([string]$FilePath, [string[]]$Arguments, [string]$ArtifactPath, [switch]$PersistOutput) {{
    return [pscustomobject]@{{
        ExitCode = 0
        Output = '[{{"Name":"[REDACTED]-t153-volume-proof_postgres-data","Labels":{{"com.docker.compose.project":"[REDACTED]-t153-volume-proof"}}}}]'
        RawOutput = '[{{"Name":"reclaim-t153-volume-proof_postgres-data","Labels":{{"com.docker.compose.project":"reclaim-t153-volume-proof"}}}}]'
    }}
}}

try {{
    $proof = Get-VolumeProof -Name 'reclaim-t153-volume-proof' -ArtifactPath '{artifact}'
    Write-Output ('proof=success:' + $proof.name)
}} catch {{
    Write-Output ('proof=failure:' + $_.Exception.Message)
    exit 1
}}
"""
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "proof=success:reclaim-t153-volume-proof_postgres-data" in result.stdout


def test_harness_persists_structured_record_without_redacting_paths(
    tmp_path: Path,
) -> None:
    """The resume record must retain paths even when a secret overlaps them."""

    pwsh = shutil.which("pwsh")
    if pwsh is None:
        raise AssertionError("pwsh is required for the PowerShell record contract")

    script = HARNESS.as_posix().replace("'", "''")
    record_path = (tmp_path / "record.json").as_posix().replace("'", "''")
    run_directory = (tmp_path / "reclaim-t153-record-test-run").as_posix().replace("'", "''")
    command = f"""
. '{script}' -DefineOnly
$env:RECLAIM_MINIO_ACCESS_KEY = 'reclaim'
function Get-ProjectRecordPath([string]$Name) {{ return '{record_path}' }}
$record = [ordered]@{{
    project = 'reclaim-t153-record-test'
    run_id = 'record-test'
    run_directory = '{run_directory}'
    state = 'prepared'
}}
Save-ProjectRecord -Record $record
$stored = Get-Content -Raw -LiteralPath '{record_path}' | ConvertFrom-Json
if ($stored.project -ne 'reclaim-t153-record-test') {{ throw "project path was redacted" }}
if ($stored.run_directory -ne '{run_directory}') {{ throw "run directory was redacted" }}
Write-Output 'record=success'
"""
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "record=success" in result.stdout
