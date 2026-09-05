[CmdletBinding()]
param(
    [string]$ProjectName = "reclaim-demo"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repositoryRoot "infra\docker-compose.yml"

docker compose -p $ProjectName -f $composeFile --profile full up -d --build --wait --wait-timeout 180 postgres redpanda redis minio api event-relay web n8n-main n8n-worker
if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed to start RECLAIM." }
docker compose -p $ProjectName -f $composeFile ps event-relay
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not verify the event relay status." }
docker compose -p $ProjectName -f $composeFile ps
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not report RECLAIM status." }

Write-Host "RECLAIM is starting at http://localhost:3000"
Write-Host "The Case Inbox is at http://localhost:3000/cases and new orchestration is owned by n8n."
Write-Host "This runtime uses PostgreSQL-backed Fresh Agent + Action Gateway Simulator/Test Mode."
Write-Host "No live merchant effects occur. If no model is configured, the run reports MODEL_UNAVAILABLE."
Write-Host "The PostgreSQL outbox relay is included in the full profile and waits for Redpanda/PostgreSQL."
Write-Host "To import workflows, set N8N_API_KEY and run .\infra\n8n\bootstrap.ps1."
