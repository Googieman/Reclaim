param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot ".."))
)

$ErrorActionPreference = "Stop"
$forbidden = @(
    "Action Gateway credentials",
    "database write",
    "shell command",
    "arbitrary network",
    "credential probing"
)
$agentPath = Join-Path $Root "backend/agent"
if (-not (Test-Path -LiteralPath $agentPath)) {
    Write-Output "Boundary check: backend/agent not present yet; no agent boundary to inspect."
    exit 0
}

$violations = foreach ($term in $forbidden) {
    Select-String -Path (Join-Path $agentPath "*.py") -Pattern $term -SimpleMatch -ErrorAction SilentlyContinue
}
if ($violations) {
    $violations | ForEach-Object { Write-Error $_.ToString() }
    exit 1
}
Write-Output "Boundary check passed: no forbidden capability markers found in agent sources."
