[CmdletBinding()]
param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [string]$ReleaseMetadata = "",
    [string]$ProductionEnv = ""
)

$ErrorActionPreference = "Stop"
$arguments = @("$PSScriptRoot/release_preflight.py", "--root", $Root)
if (-not [string]::IsNullOrWhiteSpace($ReleaseMetadata)) {
    $arguments += @("--release-metadata", $ReleaseMetadata)
}
if (-not [string]::IsNullOrWhiteSpace($ProductionEnv)) {
    $arguments += @("--production-env", $ProductionEnv)
}

python @arguments
exit $LASTEXITCODE
