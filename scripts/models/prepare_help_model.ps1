[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ArtifactDirectory,
    [string] $ManifestPath = (Join-Path $PSScriptRoot '..\..\models\help-deepseek\manifest.json'),
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

function Resolve-NormalPath([string] $PathValue) {
    return [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $PathValue -ErrorAction SilentlyContinue ?? $PathValue))
}

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
$artifactRoot = [System.IO.Path]::GetFullPath($ArtifactDirectory)
$artifactFile = Join-Path $artifactRoot $manifest.model.filename

if ($artifactRoot.StartsWith($repositoryRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Artifact directory must be outside the repository: $artifactRoot"
}
if ($manifest.status -eq 'disabled') {
    throw 'The help model manifest is disabled'
}
if ($manifest.model.sha256 -notmatch '^[0-9a-f]{64}$') {
    throw 'Manifest SHA-256 is not a full lowercase digest'
}

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$expectedBytes = [int64]$manifest.model.size_bytes
$expectedHash = $manifest.model.sha256.ToLowerInvariant()

if (Test-Path -LiteralPath $artifactFile) {
    $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifactFile).Hash.ToLowerInvariant()
    if ($existingHash -eq $expectedHash) {
        Write-Output "verified existing artifact: $artifactFile"
        exit 0
    }
    if (-not $Force) {
        throw "Existing artifact checksum mismatch. Re-run with -Force only after reviewing the replacement: $artifactFile"
    }
}

$uri = "https://huggingface.co/$($manifest.model.repository)/resolve/$($manifest.model.revision)/$($manifest.model.filename)?download=true"
$temporaryFile = Join-Path $artifactRoot (".$($manifest.model.filename).download-$([guid]::NewGuid().ToString('N'))")
try {
    Invoke-WebRequest -Uri $uri -OutFile $temporaryFile -UseBasicParsing
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporaryFile).Hash.ToLowerInvariant()
    $actualBytes = (Get-Item -LiteralPath $temporaryFile).Length
    if ($actualHash -ne $expectedHash -or $actualBytes -ne $expectedBytes) {
        throw "Downloaded artifact identity mismatch: bytes=$actualBytes sha256=$actualHash"
    }
    Move-Item -LiteralPath $temporaryFile -Destination $artifactFile -Force:$Force
    Write-Output "verified artifact: $artifactFile"
}
finally {
    if (Test-Path -LiteralPath $temporaryFile) {
        Remove-Item -LiteralPath $temporaryFile -Force
    }
}
