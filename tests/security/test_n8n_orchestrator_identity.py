"""Security regressions for the API-only n8n service identity."""

from __future__ import annotations

import json
import os
from pathlib import Path
import pytest
import shutil
import subprocess
import tempfile
from app.auth.local_demo import LocalDemoVerifier
from app.auth.oidc import IdentityType, RequiredRole, TenantAuthorizationError

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_PATH = ROOT / "infra" / "n8n" / "bootstrap.ps1"
WORKFLOW_DIR = ROOT / "infra" / "n8n" / "workflows"
PWSH = shutil.which("pwsh")


def _bootstrap_env(env_updates: dict[str, str | None]) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("N8N_API_KEY", "api-key-for-tests")
    env.setdefault("RECLAIM_N8N_SERVICE_TOKEN", "service-token-for-tests")
    env.setdefault(
        "N8N_KAFKA_CREDENTIAL_DATA_JSON",
        json.dumps(
            {
                "brokers": ["redpanda:9092"],
                "clientId": "bootstrap-test",
                "sasl": {
                    "mechanism": "plain",
                    "username": "bootstrap-user",
                    "password": "bootstrap-password",
                },
            }
        ),
    )
    for key, value in env_updates.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _run_bootstrap_direct(
    *,
    activate: bool,
    env_updates: dict[str, str | None],
) -> subprocess.CompletedProcess[str]:
    assert PWSH is not None
    return subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-File",
            str(BOOTSTRAP_PATH),
            "-N8nBaseUrl",
            "https://n8n.example.test",
            *(["-Activate"] if activate else []),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_bootstrap_env(env_updates),
    )


def _run_bootstrap_contract(
    *,
    activate: bool,
    env_updates: dict[str, str | None],
    workflows: list[dict[str, object]] | None = None,
    credentials: list[dict[str, object]] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    state = {
        "credentials": credentials or [],
        "workflows": workflows or [],
        "nextCredentialId": 1,
        "nextWorkflowId": 1,
    }
    harness = r"""
param(
    [string]$BootstrapPath,
    [string]$StatePath,
    [string]$ResultPath,
    [string]$N8nBaseUrl,
    [switch]$Activate
)

$ErrorActionPreference = "Stop"
$global:state = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json -AsHashtable
$global:calls = [System.Collections.ArrayList]::new()
$global:errorMessage = $null
$global:exitCode = 0
$global:scriptStackTrace = $null
$global:credentials = [System.Collections.ArrayList]::new()
$global:workflows = [System.Collections.ArrayList]::new()
foreach ($credential in @($global:state.credentials)) {
    [void]$global:credentials.Add($credential)
}
foreach ($workflow in @($global:state.workflows)) {
    [void]$global:workflows.Add($workflow)
}

function Get-QueryValue([string]$Uri, [string]$Name) {
    $query = ([uri]$Uri).Query.TrimStart("?")
    if ([string]::IsNullOrWhiteSpace($query)) {
        return $null
    }
    foreach ($segment in $query.Split("&", [System.StringSplitOptions]::RemoveEmptyEntries)) {
        $parts = $segment.Split("=", 2)
        if ([uri]::UnescapeDataString($parts[0]) -ne $Name) {
            continue
        }
        if ($parts.Count -lt 2) {
            return ""
        }
        return [uri]::UnescapeDataString($parts[1])
    }
    return $null
}

function Get-PaginatedResponse([System.Collections.ArrayList]$Items, [string]$Uri) {
    $limitText = Get-QueryValue -Uri $Uri -Name "limit"
    $cursorText = Get-QueryValue -Uri $Uri -Name "cursor"
    $limit = if ([string]::IsNullOrWhiteSpace($limitText)) { 100 } else { [int]$limitText }
    $start = if ([string]::IsNullOrWhiteSpace($cursorText)) { 0 } else { [int]$cursorText }
    $page = [System.Collections.ArrayList]::new()
    $end = [Math]::Min($start + $limit, $Items.Count)
    for ($index = $start; $index -lt $end; $index += 1) {
        [void]$page.Add($Items[$index])
    }
    $nextCursor = $null
    if ($end -lt $Items.Count) {
        $nextCursor = [string]$end
    }
    return @{
        data = @($page)
        nextCursor = $nextCursor
    }
}

function Add-Call([string]$Method, [string]$Uri, [string]$Body) {
    $parsedBody = $null
    if (-not [string]::IsNullOrWhiteSpace($Body)) {
        $parsedBody = $Body | ConvertFrom-Json -AsHashtable
    }
    if ($Uri -like "*/api/v1/credentials*" -and $null -ne $parsedBody) {
        $credentialData = $parsedBody.data
        if ($parsedBody.type -eq "kafka") {
            $credentialData = @{
                clientId = $credentialData.clientId
                brokers = $credentialData.brokers
                ssl = $credentialData.ssl
                authentication = $credentialData.authentication
                saslMechanism = $credentialData.saslMechanism
                username = if ($null -ne $credentialData.username) { "***REDACTED***" } else { $null }
                password = if ($null -ne $credentialData.password) { "***REDACTED***" } else { $null }
            }
        } else {
            $credentialData = "***REDACTED***"
        }
        $parsedBody = @{
            name = $parsedBody.name
            type = $parsedBody.type
            data = $credentialData
        }
    }
    [void]$global:calls.Add([pscustomobject]@{
        method = $Method
        uri = $Uri
        body = $parsedBody
    })
}

function Invoke-RestMethod {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [string]$ContentType,
        [string]$Body
    )

    Add-Call -Method $Method -Uri $Uri -Body $Body

    if ($Method -eq "Get" -and ([uri]$Uri).AbsolutePath -eq "/api/v1/credentials") {
        return Get-PaginatedResponse -Items $global:credentials -Uri $Uri
    }

    if ($Uri -like "*/api/v1/credentials" -and $Method -eq "Post") {
        $payload = $Body | ConvertFrom-Json -AsHashtable
        $id = "credential-$($global:state.nextCredentialId)"
        $global:state.nextCredentialId += 1
        $record = @{
            id = $id
            name = $payload.name
            type = $payload.type
            data = $payload.data
        }
        [void]$global:credentials.Add($record)
        return $record
    }

    if ($Uri -like "*/api/v1/credentials/*" -and $Method -eq "Put") {
        $payload = $Body | ConvertFrom-Json -AsHashtable
        $id = ($Uri.Split("/") | Select-Object -Last 1)
        $updated = $null
        for ($index = 0; $index -lt $global:credentials.Count; $index += 1) {
            if ($global:credentials[$index].id -eq $id) {
                $updated = @{
                    id = $id
                    name = $payload.name
                    type = $payload.type
                    data = $payload.data
                }
                $global:credentials[$index] = $updated
                break
            }
        }
        return $updated
    }

    if ($Method -eq "Get" -and ([uri]$Uri).AbsolutePath -eq "/api/v1/workflows") {
        return Get-PaginatedResponse -Items $global:workflows -Uri $Uri
    }

    if ($Uri -like "*/api/v1/workflows/*/activate" -and $Method -eq "Post") {
        $id = $Uri.Split("/")[-2]
        for ($index = 0; $index -lt $global:workflows.Count; $index += 1) {
            if ($global:workflows[$index].id -eq $id) {
                $global:workflows[$index].active = $true
                break
            }
        }
        return @{ data = @{ id = $id; active = $true } }
    }

    if ($Uri -like "*/api/v1/workflows/*" -and $Method -eq "Get") {
        $id = $Uri.Split("/")[-1]
        return @($global:workflows | Where-Object { $_.id -eq $id })[0]
    }

    if ($Uri -like "*/api/v1/workflows" -and $Method -eq "Post") {
        $payload = $Body | ConvertFrom-Json -AsHashtable
        $id = "workflow-$($global:state.nextWorkflowId)"
        $global:state.nextWorkflowId += 1
        $record = @{
            id = $id
            name = $payload.name
            settings = $payload.settings
            active = $false
        }
        [void]$global:workflows.Add($record)
        return $record
    }

    if ($Uri -like "*/api/v1/workflows/*" -and $Method -eq "Put") {
        $payload = $Body | ConvertFrom-Json -AsHashtable
        $id = $Uri.Split("/")[-1]
        $updated = $null
        for ($index = 0; $index -lt $global:workflows.Count; $index += 1) {
            if ($global:workflows[$index].id -eq $id) {
                $updated = @{
                    id = $id
                    name = $payload.name
                    settings = $payload.settings
                    active = [bool]$global:workflows[$index].active
                }
                $global:workflows[$index] = $updated
                break
            }
        }
        return $updated
    }

    throw "Unhandled mock request: $Method $Uri"
}

try {
    if ($Activate) {
        & $BootstrapPath -N8nBaseUrl $N8nBaseUrl -Activate
    } else {
        & $BootstrapPath -N8nBaseUrl $N8nBaseUrl
    }
} catch {
    $global:exitCode = 1
    $global:errorMessage = $_.Exception.Message
    $global:scriptStackTrace = $_.ScriptStackTrace
}

@{
    exit_code = $global:exitCode
    error_message = $global:errorMessage
    script_stack_trace = $global:scriptStackTrace
    calls = @($global:calls)
    workflows = @($global:workflows)
    credentials = @(
        foreach ($credential in @($global:credentials)) {
            @{
                id = $credential.id
                name = $credential.name
                type = $credential.type
                data = "***REDACTED***"
            }
        }
    )
} | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ResultPath -Encoding utf8
"""

    assert PWSH is not None
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        state_path = temp_path / "state.json"
        harness_path = temp_path / "harness.ps1"
        result_path = temp_path / "result.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        harness_path.write_text(harness, encoding="utf-8")
        completed = subprocess.run(
            [
                PWSH,
                "-NoProfile",
                "-File",
                str(harness_path),
                "-BootstrapPath",
                str(BOOTSTRAP_PATH),
                "-StatePath",
                str(state_path),
                "-ResultPath",
                str(result_path),
                "-N8nBaseUrl",
                "https://n8n.example.test",
                *(["-Activate"] if activate else []),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=_bootstrap_env(env_updates),
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
    return completed, result


def test_local_n8n_identity_is_service_scoped_to_orchestration() -> None:
    context = LocalDemoVerifier().authorize(
        "demo-n8n-orchestrator",
        tenant_id="tenant-1",
        required_role=RequiredRole.ORCHESTRATOR,
    )

    assert context.identity_type is IdentityType.SERVICE
    assert context.subject == "reclaim-n8n-orchestrator"
    assert context.roles == frozenset({"orchestrator"})


def test_reviewer_identity_cannot_use_the_n8n_stage_identity() -> None:
    context = LocalDemoVerifier().authorize("demo-reviewer", tenant_id="tenant-1")

    assert context.identity_type is IdentityType.USER
    with pytest.raises(TenantAuthorizationError):
        context.require_role(RequiredRole.ORCHESTRATOR)


def test_bootstrap_activation_fails_closed_when_required_inputs_are_missing() -> None:
    for missing_name in (
        "N8N_API_KEY",
        "N8N_KAFKA_CREDENTIAL_DATA_JSON",
        "RECLAIM_N8N_SERVICE_TOKEN",
    ):
        completed, result = _run_bootstrap_contract(
            activate=True,
            env_updates={missing_name: None},
        )

        assert completed.returncode == 0
        assert result["exit_code"] == 1
        assert missing_name in str(result["error_message"])


def test_bootstrap_process_requires_service_token_without_activation() -> None:
    completed = _run_bootstrap_direct(
        activate=False,
        env_updates={"RECLAIM_N8N_SERVICE_TOKEN": None},
    )

    assert completed.returncode != 0
    output = "\n".join((completed.stdout, completed.stderr))
    assert "RECLAIM_N8N_SERVICE_TOKEN" in output
    assert "service-token-for-tests" not in output


@pytest.mark.parametrize(
    "missing_name",
    (
        "N8N_API_KEY",
        "N8N_KAFKA_CREDENTIAL_DATA_JSON",
        "RECLAIM_N8N_SERVICE_TOKEN",
    ),
)
def test_bootstrap_process_exits_non_zero_when_activation_prerequisites_are_missing(
    missing_name: str,
) -> None:
    completed = _run_bootstrap_direct(
        activate=True,
        env_updates={missing_name: None},
    )

    assert completed.returncode != 0
    output = "\n".join((completed.stdout, completed.stderr))
    assert missing_name in output
    for secret in ("api-key-for-tests", "service-token-for-tests", "bootstrap-password"):
        assert secret not in output


def test_bootstrap_activation_upserts_recovery_then_handoff_and_verifies_active_state() -> None:
    completed, result = _run_bootstrap_contract(
        activate=True,
        env_updates={},
        workflows=[
            {
                "id": "workflow-recovery",
                "name": "incident-analysis-error-recovery.v1",
                "active": False,
                "settings": {},
            },
            {
                "id": "workflow-handoff",
                "name": "incident-analysis-handoff.v1",
                "active": False,
                "settings": {"errorWorkflow": "incident-analysis-error-recovery.v1"},
            },
        ],
    )

    assert completed.returncode == 0
    assert result["exit_code"] == 0

    workflow_writes = [
        call
        for call in result["calls"]
        if "/api/v1/workflows/" in call["uri"] and call["method"] == "Put"
    ]
    assert [call["body"]["name"] for call in workflow_writes] == [
        "incident-analysis-error-recovery.v1",
        "incident-analysis-handoff.v1",
    ]
    assert workflow_writes[1]["body"]["settings"]["errorWorkflow"] == "workflow-recovery"

    activation_calls = [
        call
        for call in result["calls"]
        if call["method"] == "Post" and call["uri"].endswith("/api/v1/workflows/workflow-handoff/activate")
    ]
    assert len(activation_calls) == 1

    read_calls = [
        call
        for call in result["calls"]
        if call["method"] == "Get" and call["uri"].endswith("/api/v1/workflows/workflow-handoff")
    ]
    assert len(read_calls) == 1
    handoff = next(
        workflow for workflow in result["workflows"] if workflow["id"] == "workflow-handoff"
    )
    assert handoff["active"] is True


def test_bootstrap_reuses_workflow_credential_references_without_listing_credentials() -> None:
    credentials = [
        {
            "id": f"credential-filler-{index}",
            "name": f"filler-credential-{index}",
            "type": "httpHeaderAuth",
            "data": {"name": "Authorization", "value": f"Bearer filler-{index}"},
        }
        for index in range(250)
    ]
    credentials.extend(
        (
            {
                "id": "credential-http-existing",
                "name": "reclaim-orchestrator-service",
                "type": "httpHeaderAuth",
                "data": {"name": "Authorization", "value": "Bearer existing"},
            },
            {
                "id": "credential-kafka-existing",
                "name": "reclaim-redpanda-readonly",
                "type": "kafka",
                "data": {"brokers": ["redpanda:9092"]},
            },
        )
    )
    workflows = [
        {
            "id": f"workflow-filler-{index}",
            "name": f"filler-workflow-{index}",
            "active": False,
            "settings": {},
        }
        for index in range(250)
    ]
    workflows.extend(
        (
            {
            "id": "workflow-recovery-existing",
            "name": "incident-analysis-error-recovery.v1",
            "active": False,
            "settings": {},
            "nodes": [
                {
                    "credentials": {
                        "httpHeaderAuth": {
                            "id": "credential-http-existing",
                            "name": "reclaim-orchestrator-service",
                        }
                    }
                }
            ],
        },
        {
            "id": "workflow-handoff-existing",
            "name": "incident-analysis-handoff.v1",
            "active": False,
            "settings": {"errorWorkflow": "incident-analysis-error-recovery.v1"},
            "nodes": [
                {
                    "credentials": {
                        "httpHeaderAuth": {
                            "id": "credential-http-existing",
                            "name": "reclaim-orchestrator-service",
                        },
                        "kafka": {
                            "id": "credential-kafka-existing",
                            "name": "reclaim-redpanda-readonly",
                        },
                    }
                }
            ],
        },
        )
    )

    completed, result = _run_bootstrap_contract(
        activate=True,
        env_updates={},
        workflows=workflows,
        credentials=credentials,
    )

    assert completed.returncode == 0
    assert result["exit_code"] == 0

    credential_posts = [
        call for call in result["calls"] if call["method"] == "Post" and call["uri"].endswith("/api/v1/credentials")
    ]
    workflow_posts = [
        call for call in result["calls"] if call["method"] == "Post" and call["uri"].endswith("/api/v1/workflows")
    ]
    assert credential_posts == []
    assert workflow_posts == []

    credential_put_ids = [
        call["uri"].rsplit("/", 1)[-1]
        for call in result["calls"]
        if call["method"] == "Put" and "/api/v1/credentials/" in call["uri"]
    ]
    assert credential_put_ids == []

    workflow_puts = [
        call
        for call in result["calls"]
        if call["method"] == "Put" and "/api/v1/workflows/" in call["uri"]
    ]
    assert [call["body"]["name"] for call in workflow_puts] == [
        "incident-analysis-error-recovery.v1",
        "incident-analysis-handoff.v1",
    ]
    assert workflow_puts[1]["body"]["settings"]["errorWorkflow"] == "workflow-recovery-existing"

    credential_gets = [
        call["uri"]
        for call in result["calls"]
        if call["method"] == "Get" and "/api/v1/credentials" in call["uri"]
    ]
    workflow_gets = [
        call["uri"]
        for call in result["calls"]
        if call["method"] == "Get" and "/api/v1/workflows?" in call["uri"]
    ]
    assert credential_gets == []
    assert any("cursor=" in uri for uri in workflow_gets)


def test_bootstrap_normalizes_legacy_kafka_data_for_n8n_credential_schema() -> None:
    legacy_data = json.dumps({"brokers": ["redpanda:9092"], "ssl": False})
    completed, result = _run_bootstrap_contract(
        activate=True,
        env_updates={"N8N_KAFKA_CREDENTIAL_DATA_JSON": legacy_data},
    )

    assert completed.returncode == 0
    assert result["exit_code"] == 0
    kafka_posts = [
        call
        for call in result["calls"]
        if call["method"] == "Post"
        and call["uri"].endswith("/api/v1/credentials")
        and call["body"]["type"] == "kafka"
    ]
    assert len(kafka_posts) == 1
    assert kafka_posts[0]["body"]["data"]["brokers"] == "redpanda:9092"
    assert kafka_posts[0]["body"]["data"]["ssl"] is False
    assert kafka_posts[0]["body"]["data"]["authentication"] is False


def test_bootstrap_strips_fields_not_accepted_by_n8n_workflow_write_schema() -> None:
    completed, result = _run_bootstrap_contract(
        activate=True,
        env_updates={},
    )

    assert completed.returncode == 0
    assert result["exit_code"] == 0
    allowed_fields = {
        "name",
        "nodes",
        "connections",
        "settings",
        "staticData",
    }
    workflow_writes = [
        call
        for call in result["calls"]
        if call["method"] in {"Post", "Put"}
        and "/api/v1/workflows" in call["uri"]
        and not call["uri"].endswith("/activate")
    ]
    assert len(workflow_writes) == 2
    for call in workflow_writes:
        assert set(call["body"]) <= allowed_fields
        assert "pinData" not in call["body"]
        assert "active" not in call["body"]
        assert "tags" not in call["body"]


def test_bootstrap_activation_posts_without_an_undeclared_request_body() -> None:
    completed, result = _run_bootstrap_contract(
        activate=True,
        env_updates={},
    )

    assert completed.returncode == 0
    assert result["exit_code"] == 0
    activation_calls = [
        call
        for call in result["calls"]
        if call["method"] == "Post" and call["uri"].endswith("/activate")
    ]
    assert len(activation_calls) == 1
    assert activation_calls[0]["body"] is None


def test_bootstrap_outputs_do_not_echo_supplied_secret_values() -> None:
    api_key = "api-key-secret-value"
    service_token = "service-token-secret-value"
    kafka_password = "kafka-password-secret-value"
    completed, result = _run_bootstrap_contract(
        activate=True,
        env_updates={
            "N8N_API_KEY": api_key,
            "RECLAIM_N8N_SERVICE_TOKEN": service_token,
            "N8N_KAFKA_CREDENTIAL_DATA_JSON": json.dumps(
                {
                    "brokers": ["redpanda:9092"],
                    "clientId": "bootstrap-test",
                    "sasl": {
                        "mechanism": "plain",
                        "username": "bootstrap-user",
                        "password": kafka_password,
                    },
                }
            ),
        },
    )

    assert completed.returncode == 0
    output = "\n".join((completed.stdout, completed.stderr, json.dumps(result))).lower()
    for secret in (api_key, service_token, kafka_password):
        assert secret.lower() not in output


def test_checked_in_n8n_artifacts_do_not_embed_forbidden_secret_scopes() -> None:
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in WORKFLOW_DIR.glob("*.json")
    ).lower()
    bootstrap_text = BOOTSTRAP_PATH.read_text(encoding="utf-8").lower()
    combined = f"{workflow_text}\n{bootstrap_text}"

    assert "reclaim-orchestrator-service" in combined
    assert "reclaim-redpanda-readonly" in combined
    assert "postgres" not in combined
    assert "minio" not in combined
    assert "action-gateway" not in combined
    assert "approval" not in combined
