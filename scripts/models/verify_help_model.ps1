[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ArtifactPath,
    [string] $ManifestPath = (Join-Path $PSScriptRoot '..\..\models\help-deepseek\manifest.json')
)

$ErrorActionPreference = 'Stop'

function Fail([string] $Message) {
    throw [System.InvalidOperationException]::new($Message)
}

try {
    $manifestFullPath = [System.IO.Path]::GetFullPath($ManifestPath)
    $manifest = [System.IO.File]::ReadAllText($manifestFullPath) | ConvertFrom-Json
    $model = $manifest.model

    if ($manifest.status -eq 'disabled') {
        Fail 'model manifest is disabled'
    }
    if ($model.sha256 -notmatch '^[0-9a-f]{64}$') {
        Fail 'model manifest checksum is invalid'
    }
    if ([int64]$model.size_bytes -le 0) {
        Fail 'model manifest size is invalid'
    }

    $artifactFullPath = [System.IO.Path]::GetFullPath($ArtifactPath)
    if (-not [System.IO.File]::Exists($artifactFullPath)) {
        Fail 'model artifact is missing'
    }
    $artifact = Get-Item -LiteralPath $artifactFullPath
    if ($artifact.Name -ne [string]$model.filename) {
        Fail 'model artifact filename is not the manifest filename'
    }
    if ([int64]$artifact.Length -ne [int64]$model.size_bytes) {
        Fail 'model artifact size does not match the manifest'
    }

    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifactFullPath).Hash.ToLowerInvariant()
    if ($actualHash -ne ([string]$model.sha256).ToLowerInvariant()) {
        Fail 'model artifact checksum does not match the manifest'
    }

    Write-Output 'verified help model artifact'
}
catch {
    Write-Error 'help model artifact verification failed'
    exit 1
}
