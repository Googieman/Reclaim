[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$ProjectName = "reclaim-production",
    [string]$ComposeFile = "",
    [string]$Database = "reclaim"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ComposeFile)) { $ComposeFile = Join-Path $repositoryRoot "infra\docker-compose.yml" }
if ($ProjectName -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$') { throw "Invalid RECLAIM Compose project name." }
if ($Database -notmatch '^[a-zA-Z0-9_]{1,63}$') { throw "Invalid PostgreSQL database identifier." }

$destination = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$dumpPath = Join-Path $destination "reclaim-postgresql-$stamp.dump"
$manifestPath = "$dumpPath.manifest.json"

Write-Host "Creating PostgreSQL custom-format backup for project $ProjectName."
docker compose -p $ProjectName -f $ComposeFile exec -T postgres pg_dump --format=custom --compress=zstd --no-owner --no-acl --dbname=$Database > $dumpPath
if ($LASTEXITCODE -ne 0) { Remove-Item -LiteralPath $dumpPath -Force -ErrorAction SilentlyContinue; throw "pg_dump failed; no backup was recorded." }

$hash = Get-FileHash -LiteralPath $dumpPath -Algorithm SHA256
if ($hash.Hash.Length -ne 64) { throw "SHA256 checksum was not produced." }
Get-Content -LiteralPath $dumpPath -AsByteStream -ReadCount 0 | docker compose -p $ProjectName -f $ComposeFile exec -T postgres pg_restore --list | Out-Null
if ($LASTEXITCODE -ne 0) { throw "pg_restore could not read the backup; refusing to publish it." }

@{
    schema_version = "reclaim-backup-manifest-v1"
    backup_kind = "postgresql"
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    format = "custom"
    sha256 = "sha256:$($hash.Hash.ToLowerInvariant())"
    size_bytes = (Get-Item -LiteralPath $dumpPath).Length
    source_database = $Database
    source_project = $ProjectName
    credentials_included = $false
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM

Write-Host "Backup and pg_restore integrity check completed: $dumpPath"
Write-Host "Store the dump and manifest in an encrypted, access-controlled destination outside this repository."
