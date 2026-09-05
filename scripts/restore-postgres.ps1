[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [string]$TargetDatabase,
    [switch]$Confirm,
    [string]$ProjectName = "reclaim-production",
    [string]$ComposeFile = ""
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ComposeFile)) { $ComposeFile = Join-Path $repositoryRoot "infra\docker-compose.yml" }
if (-not $Confirm) { throw "Restore is blocked until -Confirm is supplied for an isolated target." }
if ($ProjectName -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$') { throw "Invalid RECLAIM Compose project name." }
if ($TargetDatabase -notmatch '^reclaim_restore_[a-zA-Z0-9_]{1,48}$') { throw "TargetDatabase must be an isolated reclaim_restore_* database." }

$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
if ($manifest.backup_kind -ne "postgresql" -or $manifest.format -ne "custom") { throw "Unsupported backup manifest." }
$dumpPath = [System.IO.Path]::ChangeExtension($ManifestPath, $null)
if (-not (Test-Path -LiteralPath $dumpPath -PathType Leaf)) { throw "Backup dump referenced by manifest is missing." }
$hash = Get-FileHash -LiteralPath $dumpPath -Algorithm SHA256
if ("sha256:$($hash.Hash.ToLowerInvariant())" -ne [string]$manifest.sha256) { throw "Backup checksum mismatch; restore aborted." }

$exists = docker compose -p $ProjectName -f $ComposeFile exec -T postgres psql -U reclaim -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$TargetDatabase'"
if ($LASTEXITCODE -ne 0) { throw "Could not verify isolated PostgreSQL target." }
if ($exists.Trim() -eq "1") { throw "Target database already exists; restore never overwrites an existing database." }
docker compose -p $ProjectName -f $ComposeFile exec -T postgres psql -U reclaim -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $TargetDatabase" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not create isolated restore target." }

Get-Content -LiteralPath $dumpPath -AsByteStream -ReadCount 0 | docker compose -p $ProjectName -f $ComposeFile exec -T postgres pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname=$TargetDatabase
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed; the isolated target must be discarded and the incident escalated." }
Get-Content -LiteralPath $dumpPath -AsByteStream -ReadCount 0 | docker compose -p $ProjectName -f $ComposeFile exec -T postgres pg_restore --list | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Post-restore pg_restore integrity check failed." }
Write-Host "PostgreSQL restored into isolated target $TargetDatabase after SHA256 and pg_restore verification."
