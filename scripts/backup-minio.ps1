[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceAlias,
    [Parameter(Mandatory = $true)]
    [string]$Bucket,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
Write-Host "Creating RECLAIM MinIO immutable backup."
if ($SourceAlias -notmatch '^[a-zA-Z0-9_-]{1,32}$') { throw "Invalid MinIO alias." }
if ($Bucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$') { throw "Invalid MinIO bucket." }
$destination = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$snapshotPath = Join-Path $destination "minio-$Bucket-$stamp"
New-Item -ItemType Directory -Path $snapshotPath -Force | Out-Null

mc version info "$SourceAlias/$Bucket" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "MinIO versioning could not be verified; backup aborted." }
mc mirror --preserve --json --overwrite "$SourceAlias/$Bucket" $snapshotPath | Out-Null
if ($LASTEXITCODE -ne 0) { throw "MinIO immutable snapshot failed." }

$entries = @(
    Get-ChildItem -LiteralPath $snapshotPath -File -Recurse | ForEach-Object {
        $relative = $_.FullName.Substring($snapshotPath.Length).TrimStart('\', '/')
        $pathHash = [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData(
                [Text.Encoding]::UTF8.GetBytes($relative)
            )
        ).ToLowerInvariant()
        $contentHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        @{ object_key_sha256 = "sha256:$pathHash"; content_sha256 = "sha256:$contentHash"; size_bytes = $_.Length }
    }
)
$entries = @($entries | Sort-Object -Property object_key_sha256)
$serializedEntries = $entries | ConvertTo-Json -Compress -Depth 4
$aggregate = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($serializedEntries)
    )
).ToLowerInvariant()
@{
    schema_version = "reclaim-backup-manifest-v1"
    backup_kind = "minio"
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    source_bucket = $Bucket
    source_alias = $SourceAlias
    immutable_source_verified = $true
    object_count = $entries.Count
    aggregate_sha256 = "sha256:$aggregate"
    objects = $entries
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$snapshotPath\manifest.json" -Encoding utf8NoBOM
Write-Host "MinIO immutable snapshot and SHA256 manifest completed: $snapshotPath"
