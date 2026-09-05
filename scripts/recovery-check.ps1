[CmdletBinding()]
param(
    [string]$ProjectName = "reclaim-t153",
    [string]$ComposeFile = "",
    [string[]]$Services = @("api", "n8n-worker", "redis")
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ComposeFile)) { $ComposeFile = Join-Path $repositoryRoot "infra\docker-compose.yml" }
$allowed = @("api", "n8n-worker", "redis")
if ($Services.Count -eq 0 -or @($Services | Where-Object { $_ -notin $allowed }).Count -gt 0) { throw "T153 recovery check permits only API, n8n-worker, and Redis restarts." }
if ($ProjectName -notmatch '^reclaim-t153[a-zA-Z0-9_-]*$') { throw "Recovery check is limited to a T153 project." }

foreach ($service in $Services) {
    docker compose -p $ProjectName -f $ComposeFile restart $service
    if ($LASTEXITCODE -ne 0) { throw "T153 restart failed for $service." }
}
docker compose -p $ProjectName -f $ComposeFile --profile full up -d --wait $Services
if ($LASTEXITCODE -ne 0) { throw "T153 service recovery did not reach healthy state." }
$health = Invoke-RestMethod -Uri "http://127.0.0.1:18000/health/ready" -TimeoutSec 10
if ($health.live_actions_enabled -ne $false -or $health.live_financial_actions_enabled -ne $false) { throw "Recovery check observed unsafe live action settings." }
Write-Host "T153 safe service recovery check passed with live actions disabled. No volumes or authoritative state were removed."
