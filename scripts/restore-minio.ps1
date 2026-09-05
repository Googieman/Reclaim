[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SnapshotPath,
    [Parameter(Mandatory = $true)]
    [string]$TargetAlias,
    [Parameter(Mandatory = $true)]
    [string]$TargetBucket,
    [switch]$Confirm
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
Write-Host "Preparing RECLAIM MinIO isolated restore."
if (-not $Confirm) { throw "MinIO restore is blocked until -Confirm is supplied for an empty target." }
if ($TargetAlias -notmatch '^[a-zA-Z0-9_-]{1,32}$') { throw "Invalid MinIO alias." }
if ($TargetBucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$') { throw "Invalid MinIO bucket." }
$snapshot = [System.IO.Path]::GetFullPath($SnapshotPath)
$manifestPath = Join-Path $snapshot "manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "MinIO manifest is missing." }
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.backup_kind -ne "minio" -or $manifest.immutable_source_verified -ne $true) { throw "Unsupported or unverified MinIO manifest." }

$expected = @{}
foreach ($entry in @($manifest.objects)) {
    if (-not $entry.object_key_sha256 -or -not $entry.content_sha256) { throw "Incomplete MinIO checksum manifest." }
    $expected["$($entry.object_key_sha256)|$($entry.size_bytes)"] = [string]$entry.content_sha256
}
$actual = @(
    Get-ChildItem -LiteralPath $snapshot -File -Recurse | Where-Object Name -ne "manifest.json" | ForEach-Object {
        $relative = $_.FullName.Substring($snapshot.Length).TrimStart('\', '/')
        $pathHash = [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($relative))
        ).ToLowerInvariant()
        $contentHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $key = "sha256:$pathHash|$($_.Length)"
        if (-not $expected.ContainsKey($key) -or $expected[$key] -ne "sha256:$contentHash") { throw "MinIO object checksum manifest mismatch." }
        @{ object_key_sha256 = "sha256:$pathHash"; content_sha256 = "sha256:$contentHash"; size_bytes = $_.Length }
    }
) | Sort-Object -Property object_key_sha256
if ($actual.Count -ne [int]$manifest.object_count) { throw "MinIO object count does not match checksum manifest." }
$serializedActual = $actual | ConvertTo-Json -Compress -Depth 4
$aggregate = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($serializedActual))
).ToLowerInvariant()
if ("sha256:$aggregate" -ne [string]$manifest.aggregate_sha256) { throw "MinIO aggregate checksum mismatch." }

if ((mc stat "$TargetAlias/$TargetBucket" 2>$null)) { throw "Target bucket exists; restore never overwrites an existing bucket." }
mc mb --with-lock "$TargetAlias/$TargetBucket" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not create empty MinIO restore bucket." }
mc mirror --preserve --json $snapshot "$TargetAlias/$TargetBucket" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "MinIO restore failed; target must be quarantined for review." }
Write-Host "MinIO restored into new bucket $TargetAlias/$TargetBucket after checksum verification."
