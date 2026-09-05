param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot ".."))
)

$ErrorActionPreference = "Stop"
$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

function Get-RepoPath([string]$RelativePath) {
    return Join-Path $Root ($RelativePath -replace "/", [IO.Path]::DirectorySeparatorChar)
}

function Get-RepoText([string]$RelativePath) {
    $path = Get-RepoPath $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Fail "missing required file: $RelativePath"
        return ""
    }
    return Get-Content -Raw -LiteralPath $path
}

function Pass([string]$Message) {
    Write-Output "[PASS] $Message"
}

function Warn([string]$Message) {
    $warnings.Add($Message)
    Write-Output "[WARN] $Message"
}

function Skip([string]$Message) {
    Write-Output "[SKIP] $Message"
}

function Fail([string]$Message) {
    $failures.Add($Message)
    Write-Output "[FAIL] $Message"
}

function Require-File([string]$RelativePath) {
    if (Test-Path -LiteralPath (Get-RepoPath $RelativePath) -PathType Leaf) {
        Pass "required artifact exists: $RelativePath"
    } else {
        Fail "required artifact is missing: $RelativePath"
    }
}

function Require-Text([string]$RelativePath, [string[]]$Patterns, [string]$Description) {
    $text = Get-RepoText $RelativePath
    if ($text -eq "") {
        return
    }
    $missing = @($Patterns | Where-Object { $text -notmatch $_ })
    if ($missing.Count -eq 0) {
        Pass $Description
    } else {
        Fail "$Description; missing: $($missing -join ', ')"
    }
}

function Require-AnyText([string[]]$RelativePaths, [string[]]$Patterns, [string]$Description) {
    $text = ($RelativePaths | ForEach-Object { Get-RepoText $_ }) -join "`n"
    $missing = @($Patterns | Where-Object { $text -notmatch $_ })
    if ($missing.Count -eq 0) {
        Pass $Description
    } else {
        Fail "$Description; missing: $($missing -join ', ')"
    }
}

Write-Output "FS-001 artifact validation: $Root"

# Contract/version consistency is checked against the shared contract base and
# representative schemas. This intentionally never edits a contract.
$common = Get-RepoText "packages/contracts/common.py"
if ($common -match 'CONTRACT_VERSION\s*=\s*["'']1\.0\.0["'']') {
    Pass "shared contract version is 1.0.0"
} else {
    Fail "shared contract version is not the approved 1.0.0"
}
Require-Text "packages/contracts/schema_registry.py" @(
    'from \.common import CONTRACT_VERSION',
    'def is_compatible',
    'declared_parts\[0\] == supported_parts\[0\]'
) "schema registry enforces version compatibility"
Require-AnyText @(
    "packages/contracts/intake.py",
    "packages/contracts/connectors.py",
    "packages/contracts/analysis_policy.py",
    "packages/contracts/action_gateway.py",
    "packages/contracts/audit_replay.py"
) @('ContractModel', 'schema_version') "shared schemas inherit versioned contract context"

# Migration inventory and protected working-tree state.
$migrationDirectory = Get-RepoPath "backend/db/migrations"
$migrationFiles = @(Get-ChildItem -LiteralPath $migrationDirectory -Filter "*.sql" -File | Sort-Object Name)
$migrationNumbers = @($migrationFiles | ForEach-Object {
    if ($_.Name -match '^(\d{3})_') { $Matches[1] }
})
$expectedMigrations = @(1..13 | ForEach-Object { $_.ToString("000") })
if (($migrationNumbers -join ",") -ceq ($expectedMigrations -join ",")) {
    Pass "migrations 001-013 are present in order with no numeric gap"
} else {
    Fail "migration ordering/inventory mismatch: $($migrationNumbers -join ', ')"
}
Require-Text "backend/db/migrations/001_authoritative_entities.sql" @(
    'CREATE TABLE IF NOT EXISTS tenants',
    'CREATE TABLE IF NOT EXISTS action_(proposals|executions)'
) "authoritative base migration covers tenant and action state"
Require-Text "backend/db/migrations/002_tenant_isolation.sql" @(
    'ENABLE ROW LEVEL SECURITY',
    'FORCE ROW LEVEL SECURITY',
    'require_tenant_context'
) "tenant/RLS migration contains forced isolation"
Require-Text "backend/db/migrations/006_provider_correlation_schema.sql" @(
    'provider_correlation',
    'FORCE ROW LEVEL SECURITY'
) "D3 provider-correlation migration is present"
Require-Text "backend/db/migrations/010_canonical_action_identity.sql" @(
    'canonical_actions',
    'canonical_action_id'
) "canonical action identity migration is present"
Require-Text "backend/db/migrations/011_us3_approval_concurrency.sql" @(
    'approval',
    'version'
) "approval concurrency migration is present"
Require-Text "backend/db/migrations/012_us3_action_lifecycle.sql" @(
    'action',
    'verification',
    'escalation'
) "US3 action lifecycle migration is present"
Require-Text "backend/db/migrations/013_incident_intake_n8n.sql" @(
    'orchestration_runs',
    'orchestration_stage_attempts',
    'incident_type',
    'FORCE ROW LEVEL SECURITY'
) "n8n intake and authoritative orchestration migration is present"

$protectedContractStatus = @(git -C $Root status --short -- "packages/contracts/action_gateway.py")
if ($protectedContractStatus.Count -eq 1 -and $protectedContractStatus[0] -match '^\s*M\s+packages/contracts/action_gateway\.py$') {
    git -C $Root diff --cached --quiet -- "packages/contracts/action_gateway.py" | Out-Null
    $cachedContractExit = $LASTEXITCODE
    if ($cachedContractExit -eq 0) {
        Pass "protected Action Gateway contract remains dirty but unstaged"
    } else {
        Fail "protected Action Gateway contract is staged"
    }
} else {
    Fail "protected Action Gateway contract working-tree state changed unexpectedly"
}
$protectedMigrationStatus = @(git -C $Root status --short -- "backend/db/migrations/011_us3_approval_concurrency.sql" "backend/db/migrations/012_us3_action_lifecycle.sql")
if ($protectedMigrationStatus.Count -eq 2 -and ($protectedMigrationStatus | Where-Object { $_ -notmatch '^\?\? ' }).Count -eq 0) {
    Pass "pre-existing migrations 011/012 remain untracked and unmodified"
} else {
    Fail "protected migrations 011/012 are not in their preserved untracked state"
}
$securityStatus = @(git -C $Root status --short -- "security-audits")
if ($securityStatus.Count -gt 0 -and ($securityStatus | Where-Object { $_ -notmatch '^\?\? ' }).Count -eq 0) {
    Pass "security-audits remains intentionally untracked and untouched"
} else {
    Fail "security-audits working-tree state is not the preserved untracked state"
}

# Requirement/task traceability and task status.
$tasks = Get-RepoText "specs/001-incident-intake-containment/tasks.md"
$traceability = Get-RepoText "docs/architecture/fs001-traceability.md"
$missingFrTasks = @((1..32 | ForEach-Object { "FR-{0:D3}" -f $_ }) | Where-Object { $tasks -notmatch [regex]::Escape($_) })
$missingFrDocs = @((1..32 | ForEach-Object { "FR-{0:D3}" -f $_ }) | Where-Object { $traceability -notmatch [regex]::Escape($_) })
if ($missingFrTasks.Count -eq 0 -and $missingFrDocs.Count -eq 0) {
    Pass "FR-001 through FR-032 are present in task and documentation traceability"
} else {
    Fail "task/documentation FR traceability is incomplete"
}
$taskLines = $tasks -split "`r?`n"
$unchecked = @($taskLines | Select-String -Pattern '^- \[ \] T(\d{3})' | ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value })
$legacyUnchecked = @($unchecked | Where-Object { [int]$_ -lt 142 })
$implementationUnchecked = @($unchecked | Where-Object { [int]$_ -ge 142 -and [int]$_ -notin @(153, 154) })
$environmentGatedUnchecked = @($unchecked | Where-Object { [int]$_ -in @(153, 154) })
if ($legacyUnchecked.Count -eq 0 -and $implementationUnchecked.Count -eq 0) {
    Pass "FS-001 implementation tasks through the n8n amendment are marked complete"
} else {
    Fail "unexpected incomplete implementation tasks: $($legacyUnchecked + $implementationUnchecked -join ', ')"
}
if ($environmentGatedUnchecked.Count -gt 0) {
    Warn "environment-gated n8n qualification tasks remain open: $($environmentGatedUnchecked -join ', ')"
}

# Terminal-state authority: the word closed may be a forbidden alias, but no
# implementation may accept it as a terminal outcome.
$terminal = Get-RepoText "backend/cases/terminal_states.py"
if ($terminal -match 'verified_contained' -and $terminal -match 'verified_failed' -and $terminal -match 'escalated_unresolved' -and $terminal -match 'requested_state\s+not\s+in\s+APPROVED_TERMINAL_STATES') {
    Pass "terminal authority lists only the three explicit outcomes"
} else {
    Fail "terminal authority does not expose the required explicit outcomes"
}
$semanticClosed = @(rg -n --glob "*.py" '(?i)(terminal_state|terminal_outcome)\s*[:=]\s*["'']closed["'']|["'']closed["'']\s*(?:[:=].*)?(?:terminal_state|terminal_outcome)' (Get-RepoPath "backend") 2>$null)
if ($semanticClosed.Count -eq 0) {
    Pass "no implementation terminal field accepts generic closed"
} else {
    Fail "generic closed terminal use found in implementation"
}

# Safe defaults and replay/live truthfulness.
Require-Text "backend/app/config.py" @(
    'live_actions_enabled: bool = False',
    'live_financial_actions_enabled: bool = False'
) "backend live-action defaults are disabled"
Require-Text "infra/.env.example" @(
    'RECLAIM_LIVE_ACTIONS_ENABLED=false',
    'RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED=false'
) "environment example keeps live actions disabled"
Require-AnyText @("infra/docker-compose.yml", "infra/docker-compose.test.yml", ".github/workflows/ci.yml", ".github/workflows/security.yml", ".github/workflows/evaluation.yml") @(
    'RECLAIM_LIVE_ACTIONS_ENABLED[^\r\n]*(?:false|:-false)',
    'RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED[^\r\n]*(?:false|:-false)'
) "Compose and CI artifacts preserve disabled live-action defaults"
Require-Text "backend/replay/mode_selection.py" @(
    'live_execution_occurred=False',
    'live_financial_actions_enabled=False',
    'final_mode="replay"'
) "mode selection fails closed to replay when live qualification is absent"
Require-Text "backend/replay/runner.py" @(
    'remote_side_effects": ()',
    'side_effects": False',
    'label": "replay"'
) "replay runner preserves replay labels and no-side-effect semantics"

# Held-out sealing and provenance artifacts.
Require-Text "evaluation/manifest.yaml" @(
    'case_count: 0',
    'available_case_count: 0',
    'held_out_sealed: true',
    'assignments_frozen_before_overlay: true'
) "evaluation manifest reports actual empty corpus and sealed held-out boundary"
Require-Text "evaluation/sealed_store.py" @(
    'only held-out inputs may be stored',
    'authorize_final_evaluation'
) "sealed store requires the final-evaluation authorization path"
Require-Text "backend/observability/evaluation.py" @(
    'held_out_input',
    'held_out_seed',
    'raw_evidence',
    'non_authoritative'
) "evaluation observability drops held-out/raw values and remains non-authoritative"
$heldOutPayloadFiles = @(rg --files (Get-RepoPath "evaluation") 2>$null | Where-Object { $_ -match '(?i)held.?out.*\.(json|csv|parquet|ndjson)$' })
if ($heldOutPayloadFiles.Count -eq 0) {
    Pass "no unsealed held-out payload file is present under evaluation"
} else {
    Fail "unsealed held-out payload file found: $($heldOutPayloadFiles.FullName -join ', ')"
}

# Required validation, operator, evaluation, and isolation artifacts.
@(
    "docs/validation/us1-intake-timeline.md",
    "docs/validation/us3-containment.md",
    "docs/validation/fs001-quickstart.md",
    "docs/validation/performance-baseline.md",
    "docs/architecture/fs001-traceability.md",
    "docs/architecture/fs001-boundaries.md",
    "docs/operator/reviewer-workflow.md",
    "docs/operator/replay-and-escalation.md",
    "evaluation/manifest.schema.json",
    "evaluation/manifest.yaml",
    "evaluation/runner.py",
    "evaluation/metrics.py",
    "evaluation/report.py",
    "evaluation/sealed_store.py",
    "tests/acceptance/test_fs001_complete_flow.py",
    "infra/n8n/README.md",
    "infra/n8n/bootstrap.ps1",
    "frontend/src/app/cases/page.tsx",
    "frontend/src/components/cases/CaseInbox.tsx"
) | ForEach-Object { Require-File $_ }
Require-Text "backend/api/control_plane.py" @(
    'ActionGateway',
    'gateway_authorization_context',
    'authorization_context.require_role'
) "Action Gateway control-plane isolation is present"
Require-Text "infra/security/service-accounts.yml" @(
    'action_connector_credentials: true',
    'sole_principal',
    'merchant_mutation: false'
) "service-account matrix reserves mutation credentials for the gateway"
Require-Text "tests/security/test_approval_separation.py" @(
    'proposer_id',
    'execution_authorized is False'
) "approval separation evidence is present"
Require-Text "tests/acceptance/test_fs001_complete_flow.py" @(
    'malicious',
    'legitimate',
    'uncertain',
    'reconciled_before_retry',
    'escalated_unresolved',
    'remote_side_effects',
    'trace_correlation'
) "final mixed-activity acceptance evidence covers required safety invariants"

# Governance is intentionally amended by the n8n migration request. Validate the
# resulting policy and decision rather than rejecting the requested change.
Require-Text ".specify/memory/constitution.md" @(
    'Version\*\*:\s*2\.0\.0',
    'n8n MUST own project-wide durable',
    'Temporal is a legacy drain path'
) "constitution v2.0.0 records n8n ownership and Temporal drain"
Require-Text "specs/001-incident-intake-containment/decisions/ADR-004-n8n-orchestration-boundary.md" @(
    'n8n owns durable orchestration',
    'no direct PostgreSQL',
    'Action Gateway credentials'
) "ADR-004 records the n8n API-only boundary"
Require-Text "infra/n8n/workflows/incident-analysis-handoff.v1.json" @(
    'kafkaTrigger',
    'incident.accepted',
    'human_handoff',
    'RECLAIM_API_BASE_URL'
) "versioned n8n handoff workflow is present"
Require-Text "infra/n8n/workflows/incident-analysis-error-recovery.v1.json" @(
    'Error Trigger',
    'requires_attention',
    'failure_code'
) "versioned n8n recovery workflow is present"
$savedErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$diffCheck = @(git -C $Root diff --check -- 2>&1)
$diffExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorActionPreference
if ($diffExitCode -eq 0) {
    Pass "git diff --check passed"
} else {
    Fail "git diff --check failed: $($diffCheck -join ' ')"
}

if ($failures.Count -gt 0) {
    Write-Output "FS-001 artifact validation FAILED ($($failures.Count) failure(s), $($warnings.Count) warning(s))."
    exit 1
}
Write-Output "FS-001 artifact validation PASSED ($($warnings.Count) warning(s))."
exit 0
