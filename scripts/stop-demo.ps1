[CmdletBinding()]
param(
    [string]$ProjectName = "reclaim-demo"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repositoryRoot "infra\docker-compose.yml"

# Stop only the demo containers. Named volumes are deliberately retained.
docker compose -p $ProjectName -f $composeFile --profile full stop n8n-worker n8n-main web event-relay api minio redis redpanda postgres
if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed to stop RECLAIM." }

Write-Host "RECLAIM demo stopped. Database volumes were retained."
