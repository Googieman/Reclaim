[CmdletBinding()]
param(
    [string]$ProjectName = "reclaim-demo"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repositoryRoot "infra\docker-compose.yml"

docker compose -p $ProjectName -f $composeFile ps
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not report RECLAIM status." }

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 3
$health | ConvertTo-Json
} catch {
    Write-Warning "The API readiness endpoint is not reachable yet: $($_.Exception.Message)"
}

docker compose -p $ProjectName -f $composeFile --profile full ps postgres redpanda redis minio api event-relay web n8n-main n8n-worker
if ($LASTEXITCODE -ne 0) { throw "Docker Compose could not report RECLAIM full-stack status." }
