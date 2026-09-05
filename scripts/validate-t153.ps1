[CmdletBinding()]
param(
    [switch]$Prepare,
    [switch]$Run,
    [switch]$Cleanup,
    [switch]$DefineOnly,
    [string]$ProjectName,
    [string]$RunId
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeBase = Join-Path $repositoryRoot "infra\docker-compose.yml"
$composeOverlay = Join-Path $repositoryRoot "infra\docker-compose.t153.yml"
$t153Root = Join-Path $repositoryRoot "tmp\t153"
$t153ServiceInventory = @(
    "postgres", "redpanda", "redis", "minio", "api", "web", "event-relay", "n8n-main", "n8n-worker"
)
$secretEnvironmentNames = @(
    "N8N_API_KEY",
    "N8N_KAFKA_CREDENTIAL_DATA_JSON",
    "RECLAIM_N8N_SERVICE_TOKEN",
    "N8N_ENCRYPTION_KEY",
    "N8N_DB_PASSWORD",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "RECLAIM_MINIO_ACCESS_KEY",
    "RECLAIM_MINIO_SECRET_KEY"
)
# The live acceptance tests need MinIO credentials to verify the immutable raw
# report. Keep those two values process-only and never include them in recorded
# command output; clear all other secret variables before spawning public gates.
$publicGateSecretEnvironmentNames = @(
    "RECLAIM_MINIO_ACCESS_KEY",
    "RECLAIM_MINIO_SECRET_KEY"
)
$publicEndpointEnvironmentNames = @(
    "RECLAIM_T153_API_BASE_URL",
    "RECLAIM_T153_WEB_BASE_URL",
    "RECLAIM_DATABASE_URL",
    "RECLAIM_REDPANDA_BROKERS",
    "RECLAIM_MINIO_ENDPOINT",
    "RECLAIM_T153_PROJECT_NAME",
    "RECLAIM_T153_RUN_ID"
)
# T153 captures Docker Engine/Compose versions, image IDs/digests, container health,
# git commit/dirty-path metadata, and exit codes without persisting raw narrative.
# Failure artifacts are preserved; no automatic cleanup is performed on failure.
$script:secretValueCache = @()
$script:recordedCommandEvidence = @()
$script:lastRecordedCommand = $null

function Assert-SafeProjectName([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name -notmatch '^reclaim-t153-[a-z0-9-]+$') {
        throw "ProjectName must match ^reclaim-t153-[a-z0-9-]+$."
    }
}

function Assert-ExactlyOneMode {
    $selected = @($Prepare.IsPresent, $Run.IsPresent, $Cleanup.IsPresent) | Where-Object { $_ }
    if ($selected.Count -ne 1) {
        throw "Specify exactly one of -Prepare, -Run, or -Cleanup."
    }
}

function Assert-RequiredEnvironment([string[]]$Names) {
    foreach ($name in $Names) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "Process"))) {
            throw "$name is required in the process environment."
        }
    }
}

function Get-ComposeEnvFilePaths {
    $paths = foreach ($candidate in @(
        (Join-Path $repositoryRoot ".env"),
        (Join-Path $repositoryRoot "infra\.env")
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return @($paths | Select-Object -Unique)
}

function Get-SecretValues {
    $values = [System.Collections.Generic.List[string]]::new()
    foreach ($cachedValue in $script:secretValueCache) {
        if (-not [string]::IsNullOrWhiteSpace($cachedValue)) {
            [void]$values.Add($cachedValue)
        }
    }
    foreach ($knownDevelopmentSecret in @(
        "reclaim-development",
        "reclaim-n8n-development",
        "reclaim-n8n-development-key-change-me",
        "demo-n8n-orchestrator"
    )) {
        [void]$values.Add($knownDevelopmentSecret)
    }
    foreach ($name in $secretEnvironmentNames) {
        $value = [Environment]::GetEnvironmentVariable($name, "Process")
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            [void]$values.Add($value)
        }
    }
    foreach ($envFile in (Get-ComposeEnvFilePaths)) {
        try {
            $lines = Get-Content -LiteralPath $envFile -ErrorAction Stop
        } catch {
            continue
        }
        foreach ($line in $lines) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
                $name = $Matches[1]
                if ($secretEnvironmentNames -notcontains $name) {
                    continue
                }
                $value = $Matches[2].Trim()
                if ($value.Length -ge 2) {
                    $first = $value.Substring(0, 1)
                    $last = $value.Substring($value.Length - 1, 1)
                    if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                        $value = $value.Substring(1, $value.Length - 2)
                    }
                }
                if (-not [string]::IsNullOrWhiteSpace($value)) {
                    [void]$values.Add($value)
                }
            }
        }
    }
    $script:secretValueCache = @($values | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    return $script:secretValueCache
}

function Redact-Text([string]$Text) {
    if ($null -eq $Text) {
        return ""
    }

    $redacted = $Text
    foreach ($secret in (Get-SecretValues)) {
        $redacted = $redacted -replace [regex]::Escape($secret), "[REDACTED]"
    }
    $redacted = $redacted -replace '(?i)(bearer\s+)[^\s"'']+', '$1[REDACTED]'
    $redacted = $redacted -replace '(?i)(api[_-]?key\s*[:=]\s*)[^\s,;"'']+', '$1[REDACTED]'
    $redacted = $redacted -replace '(?i)(password|secret|service[_-]?token)\s*[:=]\s*[^\s,;"'']+', '$1=[REDACTED]'
    $redacted = $redacted -replace '(?is)(raw\s+narrative|narrative)\s*[:=]\s*.*', '$1=[REDACTED]'
    return $redacted
}

function Write-SanitizedArtifact([string]$Path, [string]$Text) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Set-Content -LiteralPath $Path -Value (Redact-Text $Text) -Encoding utf8
}

function Write-StructuredArtifact([string]$Path, [string]$Text) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    Set-Content -LiteralPath $Path -Value $Text -Encoding utf8
}

function Invoke-RecordedCommand(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$ArtifactPath,
    [switch]$PersistOutput
) {
    $nativeErrorPreference = $PSNativeCommandUseErrorActionPreference
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $capturedLines = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $PSNativeCommandUseErrorActionPreference = $nativeErrorPreference
    }
    $output = ($capturedLines | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    $sanitized = Redact-Text $output
    $script:lastRecordedCommand = [ordered]@{
        command = Redact-Text ((@($FilePath) + $Arguments) -join " ")
        exit_code = $exitCode
    }
    $script:recordedCommandEvidence += $script:lastRecordedCommand
    if ($PersistOutput) {
        Write-SanitizedArtifact -Path $ArtifactPath -Text ("COMMAND: {0} {1}`nEXIT_CODE: {2}`n{3}" -f $FilePath, ($Arguments -join " "), $exitCode, $sanitized)
    }
    Write-Host ("{0} exit code={1}" -f $FilePath, $exitCode)
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $sanitized
        # Machine validation must use the unsanitized result in memory. The raw
        # value is never persisted or written to the console.
        RawOutput = $output
    }
}

function Invoke-Compose([string[]]$Arguments, [string]$ArtifactPath, [switch]$PersistOutput) {
    return Invoke-RecordedCommand -FilePath "docker" -Arguments (@("compose") + $Arguments) -ArtifactPath $ArtifactPath -PersistOutput:$PersistOutput
}

function Assert-CommandSucceeded([pscustomobject]$Result, [string]$Description) {
    if ($Result.ExitCode -ne 0) {
        throw "$Description failed with exit code $($Result.ExitCode)."
    }
}

function Get-ComposeArguments([string]$Name) {
    return @(
        "-p", $Name,
        "-f", $composeBase,
        "-f", $composeOverlay,
        "--profile", "t153"
    )
}

function Get-RunDirectory([string]$Value) {
    return Join-Path $t153Root $Value
}

function Get-ProjectRecordPath([string]$Name) {
    return Join-Path $t153Root ("{0}.json" -f $Name)
}

function Normalize-ProjectRecord([hashtable]$Record, [string]$Name) {
    # The machine record contains only structured metadata; restore canonical
    # paths if an older sanitized record redacted values needed for -Run.
    $Record.project = $Name
    $runId = [string]$Record.run_id
    if (-not [string]::IsNullOrWhiteSpace($runId) -and $runId -match '^[A-Za-z0-9-]+$') {
        $Record.run_directory = Get-RunDirectory -Value $runId
    }
    return $Record
}

function Get-NamedVolume([string]$Name, [string]$Key) {
    return "{0}_{1}" -f $Name, $Key
}

function Get-VolumeProof([string]$Name, [string]$ArtifactPath) {
    $volumeName = Get-NamedVolume -Name $Name -Key "postgres-data"
    $result = Invoke-RecordedCommand -FilePath "docker" -Arguments @("volume", "inspect", $volumeName) -ArtifactPath $ArtifactPath -PersistOutput
    Assert-CommandSucceeded -Result $result -Description "PostgreSQL project volume inspection"
    try {
        $records = @($result.RawOutput | ConvertFrom-Json)
    } catch {
        throw "PostgreSQL project volume proof was not valid JSON."
    }
    if ($records.Count -ne 1 -or $records[0].Name -ne $volumeName) {
        throw "PostgreSQL volume proof did not identify the expected project-named volume."
    }
    if ($records[0].Labels.'com.docker.compose.project' -ne $Name) {
        throw "PostgreSQL volume is not labeled for the requested Compose project."
    }
    return [ordered]@{
        name = $volumeName
        project = $Name
        compose_volume_key = "postgres-data"
        created_by_project = $true
    }
}

function Get-HostMetadata([string]$ArtifactDirectory) {
    $dockerVersion = Invoke-RecordedCommand -FilePath "docker" -Arguments @("version", "--format", "{{.Server.Version}}") -ArtifactPath (Join-Path $ArtifactDirectory "docker-version.txt") -PersistOutput
    $composeVersion = Invoke-RecordedCommand -FilePath "docker" -Arguments @("compose", "version") -ArtifactPath (Join-Path $ArtifactDirectory "compose-version.txt") -PersistOutput
    $gitCommit = Invoke-RecordedCommand -FilePath "git" -Arguments @("rev-parse", "HEAD") -ArtifactPath (Join-Path $ArtifactDirectory "git-commit.txt") -PersistOutput
    $dirtyPaths = Invoke-RecordedCommand -FilePath "git" -Arguments @("status", "--short") -ArtifactPath (Join-Path $ArtifactDirectory "git-dirty-paths.txt") -PersistOutput

    $cpu = "unavailable"
    $memoryBytes = "unavailable"
    try {
        $cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        $memoryBytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    } catch {
        $cpu = "unavailable"
    }

    return [ordered]@{
        docker_engine = $dockerVersion.Output.Trim()
        docker_compose = $composeVersion.Output.Trim()
        host_cpu_logical_processors = $cpu
        host_memory_bytes = $memoryBytes
        git_commit = $gitCommit.Output.Trim()
        git_dirty_paths = @($dirtyPaths.Output -split "`r?`n" | Where-Object { $_ })
    }
}

function Get-Ports {
    function Get-PortValue([string]$Name, [string]$Default) {
        $value = [Environment]::GetEnvironmentVariable($Name, "Process")
        if ([string]::IsNullOrWhiteSpace($value)) {
            return $Default
        }
        return $value
    }
    return [ordered]@{
        web = "http://127.0.0.1:$(Get-PortValue -Name 'RECLAIM_WEB_PORT' -Default '13000')"
        api = "http://127.0.0.1:$(Get-PortValue -Name 'RECLAIM_API_PORT' -Default '18000')"
        postgres = "127.0.0.1:$(Get-PortValue -Name 'RECLAIM_POSTGRES_PORT' -Default '15432')"
        redpanda = "127.0.0.1:$(Get-PortValue -Name 'RECLAIM_REDPANDA_PORT' -Default '19092')"
        minio = "127.0.0.1:$(Get-PortValue -Name 'RECLAIM_MINIO_PORT' -Default '19000')"
        n8n = "http://127.0.0.1:$(Get-PortValue -Name 'RECLAIM_N8N_PORT' -Default '15678')"
    }
}

function Save-ProjectRecord([hashtable]$Record) {
    # Do not run the structured control-plane record through Redact-Text:
    # secret overlap with a project name or filesystem path would make -Run
    # follow an invalid path. Command output remains sanitized separately.
    $recordJson = $Record | ConvertTo-Json -Depth 12
    Write-StructuredArtifact -Path (Get-ProjectRecordPath -Name $Record.project) -Text $recordJson
    Write-StructuredArtifact -Path (Join-Path $Record.run_directory "metadata.json") -Text $recordJson
}

function Set-PublicTestEnvironment([hashtable]$Record) {
    $ports = $Record.ports
    $env:RECLAIM_T153_API_BASE_URL = $ports.api
    $env:RECLAIM_T153_WEB_BASE_URL = $ports.web
    $env:RECLAIM_DATABASE_URL = "postgresql://reclaim:reclaim@$($ports.postgres)/reclaim"
    $env:RECLAIM_REDPANDA_BROKERS = $ports.redpanda
    $env:RECLAIM_MINIO_ENDPOINT = $ports.minio
    $env:RECLAIM_T153_PROJECT_NAME = $Record.project
    $env:RECLAIM_T153_RUN_ID = $Record.run_id
}

function Invoke-PublicGate([string]$Label, [string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory, [string]$ArtifactDirectory) {
    Push-Location $WorkingDirectory
    try {
        $result = Invoke-RecordedCommand -FilePath $FilePath -Arguments $Arguments -ArtifactPath (Join-Path $ArtifactDirectory ("{0}.txt" -f $Label))
    } finally {
        Pop-Location
    }
    Write-SanitizedArtifact -Path (Join-Path $ArtifactDirectory ("{0}-result.txt" -f $Label)) -Text ("gate={0}`nexit code={1}" -f $Label, $result.ExitCode)
    return $result
}

function Assert-RequiredGateArtifacts {
    $task5Artifacts = @(
        "tests/acceptance/test_t153_n8n_runtime.py",
        "tests/acceptance/test_t153_restart_recovery.py"
    )
    $missingTask5 = @($task5Artifacts | Where-Object { -not (Test-Path -LiteralPath (Join-Path $repositoryRoot $_) -PathType Leaf) })
    if ($missingTask5.Count -gt 0) {
        throw "Task 5 acceptance artifacts are missing: $($missingTask5 -join ', ')."
    }

    $task7Artifacts = @(
        "frontend/playwright.t153.config.ts",
        "frontend/src/components/cases/CaseInbox.live.browser.spec.ts",
        "frontend/src/app/cases/[caseId]/CaseDetail.live.browser.spec.ts"
    )
    $missingTask7 = @($task7Artifacts | Where-Object { -not (Test-Path -LiteralPath (Join-Path $repositoryRoot $_) -PathType Leaf) })
    $packageJson = Join-Path $repositoryRoot "frontend\package.json"
    $browserScriptAvailable = $false
    if (Test-Path -LiteralPath $packageJson -PathType Leaf) {
        $package = Get-Content -Raw -LiteralPath $packageJson | ConvertFrom-Json
        $browserScriptAvailable = $null -ne $package.scripts.'test:browser:t153'
    }
    if (-not $browserScriptAvailable) {
        $missingTask7 += "frontend/package.json script test:browser:t153"
    }
    if ($missingTask7.Count -gt 0) {
        throw "Task 7 live browser artifacts are missing: $($missingTask7 -join ', ')."
    }
}

function Invoke-RunGates([hashtable]$Record, [string]$ArtifactDirectory) {
    Assert-RequiredGateArtifacts
    [void](Get-SecretValues)
    $savedEnvironment = @{}
    $secretEnvironmentNamesToClear = @($secretEnvironmentNames | Where-Object {
        $publicGateSecretEnvironmentNames -notcontains $_
    })
    foreach ($name in $secretEnvironmentNamesToClear) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    try {
        Set-PublicTestEnvironment -Record $Record

        $backendTests = @(
            "tests/acceptance/test_t153_n8n_runtime.py",
            "tests/acceptance/test_t153_restart_recovery.py"
        )
        $gateResults = [ordered]@{}
        $backend = Invoke-PublicGate -Label "backend" -FilePath "python" -Arguments (@("-m", "pytest") + $backendTests + @("-q")) -WorkingDirectory $repositoryRoot -ArtifactDirectory $ArtifactDirectory
        $gateResults.backend_exit_code = $backend.ExitCode
        Assert-CommandSucceeded -Result $backend -Description "T153 backend gates"

        $browser = Invoke-PublicGate -Label "browser" -FilePath "npm" -Arguments @("run", "test:browser:t153") -WorkingDirectory (Join-Path $repositoryRoot "frontend") -ArtifactDirectory $ArtifactDirectory
        $gateResults.browser_exit_code = $browser.ExitCode
        Assert-CommandSucceeded -Result $browser -Description "T153 live Playwright gate"
        return $gateResults
    } finally {
        foreach ($name in $secretEnvironmentNamesToClear) {
            [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], "Process")
        }
    }
}

function Save-FailedProjectRecord([string]$Name, [string]$FailureMessage, [int]$ExitCode) {
    $recordPath = Get-ProjectRecordPath -Name $Name
    if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) {
        return
    }

    try {
        $record = Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json -AsHashtable
    } catch {
        $record = [ordered]@{
            project = $Name
            run_directory = $t153Root
        }
    }
    $record = Normalize-ProjectRecord -Record $record -Name $Name
    $safeMessage = Redact-Text $FailureMessage
    $record.state = "failed"
    $record.failed_at_utc = (Get-Date -AsUTC).ToString("o")
    $record.sanitized_summary = $true
    $record.failure = [ordered]@{
        message = $safeMessage
        exit_code = $ExitCode
        command = if ($null -ne $script:lastRecordedCommand) { $script:lastRecordedCommand.command } else { "preflight" }
    }
    $record.gate_exit_evidence = @($script:recordedCommandEvidence)
    Save-ProjectRecord -Record $record

    $failureDirectory = $record.run_directory
    if ([string]::IsNullOrWhiteSpace($failureDirectory) -or -not (Test-Path -LiteralPath $failureDirectory -PathType Container)) {
        $failureDirectory = $t153Root
    }
    Write-SanitizedArtifact -Path (Join-Path $failureDirectory "failure.json") -Text ($record | ConvertTo-Json -Depth 12)
    Write-Host "T153 validation failed; preserving T153 project and volumes. Cleanup requires explicit -Cleanup."
}

function Prepare-T153 {
    if (-not (Test-Path $composeBase) -or -not (Test-Path $composeOverlay)) {
        throw "Required Compose files are missing."
    }
    if ([string]::IsNullOrWhiteSpace($RunId)) {
        $RunId = "{0}-{1}" -f (Get-Date -AsUTC -Format "yyyyMMddTHHmmssZ"), (Get-Random -Minimum 100000 -Maximum 999999)
    }
    if ($RunId -notmatch '^[A-Za-z0-9-]+$') {
        throw "RunId may contain only letters, digits, and hyphens."
    }
    $runDirectory = Get-RunDirectory -Value $RunId
    if (Test-Path $runDirectory) {
        throw "Run directory already exists; refusing to reuse a validation run."
    }
    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    $env:COMPOSE_PROJECT_NAME = $ProjectName
    $composeArgs = Get-ComposeArguments -Name $ProjectName
    $volumeName = Get-NamedVolume -Name $ProjectName -Key "postgres-data"
    # docker volume inspect proves the project-named PostgreSQL volume is absent before Prepare.
    $existingVolume = Invoke-RecordedCommand -FilePath "docker" -Arguments @("volume", "inspect", $volumeName) -ArtifactPath (Join-Path $runDirectory "preflight-volume.txt") -PersistOutput
    if ($existingVolume.ExitCode -eq 0) {
        throw "Fresh PostgreSQL volume already exists: $volumeName"
    }

    $mergedConfig = Invoke-Compose -Arguments ($composeArgs + @("config")) -ArtifactPath (Join-Path $runDirectory "merged-config.yml") -PersistOutput
    Assert-CommandSucceeded -Result $mergedConfig -Description "merged T153 Compose config"
    $up = Invoke-Compose -Arguments ($composeArgs + @("up", "-d", "--build", "--wait", "--wait-timeout", "180") + $t153ServiceInventory) -ArtifactPath (Join-Path $runDirectory "prepare-up.txt") -PersistOutput
    Assert-CommandSucceeded -Result $up -Description "T153 source-built Compose startup"
    $health = Invoke-Compose -Arguments ($composeArgs + @("ps") + $t153ServiceInventory) -ArtifactPath (Join-Path $runDirectory "container-health.txt") -PersistOutput
    Assert-CommandSucceeded -Result $health -Description "T153 container health report"
    $volumeProof = Get-VolumeProof -Name $ProjectName -ArtifactPath (Join-Path $runDirectory "postgres-volume-proof.txt")
    $images = Invoke-Compose -Arguments ($composeArgs + @("images", "--format", "json")) -ArtifactPath (Join-Path $runDirectory "image-ids-digests.json") -PersistOutput
    Assert-CommandSucceeded -Result $images -Description "T153 image metadata capture"
    $hostMetadata = Get-HostMetadata -ArtifactDirectory $runDirectory
    $ports = Get-Ports
    $record = [ordered]@{
        project = $ProjectName
        run_id = $RunId
        run_directory = $runDirectory
        state = "prepared"
        started_at_utc = (Get-Date -AsUTC).ToString("o")
        finished_at_utc = (Get-Date -AsUTC).ToString("o")
        ports = $ports
        service_inventory = $t153ServiceInventory
        postgres_volume = $volumeProof
        host = $hostMetadata
        image_metadata_artifact = (Join-Path $runDirectory "image-ids-digests.json")
        merged_config_artifact = (Join-Path $runDirectory "merged-config.yml")
        action_flags = @{
            RECLAIM_LIVE_ACTIONS_ENABLED = $false
            RECLAIM_LIVE_FINANCIAL_ACTIONS_ENABLED = $false
            RECLAIM_LIVE_ACTION_ENABLED = $false
        }
        test_exit_codes = @{}
    }
    if ([string]::IsNullOrWhiteSpace($env:N8N_API_KEY)) {
        $record.state = "awaiting_n8n_operator_setup"
        $record.operator_url = $ports.n8n
        Write-Host "state=awaiting_n8n_operator_setup"
        Write-Host "Open the loopback n8n operator URL: $($ports.n8n)"
        Write-Host "Create the owner and API key in n8n out of band; the harness will never invent or scrape one."
    }
    Save-ProjectRecord -Record $record
    Write-Host "Prepared T153 project=$ProjectName run_id=$RunId state=$($record.state)"
}

function Run-T153 {
    $recordPath = Get-ProjectRecordPath -Name $ProjectName
    if (-not (Test-Path $recordPath)) {
        throw "No prepared T153 project record exists for $ProjectName."
    }
    $record = Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json -AsHashtable
    $record = Normalize-ProjectRecord -Record $record -Name $ProjectName
    $env:COMPOSE_PROJECT_NAME = $ProjectName
    $runDirectory = $record.run_directory
    $priorState = $record.state
    $record.state = "in_progress"
    $record.run_started_at_utc = (Get-Date -AsUTC).ToString("o")
    $record.sanitized_summary = $true
    $record.test_exit_codes = @{}
    Save-ProjectRecord -Record $record

    try {
        if ($priorState -eq "awaiting_n8n_operator_setup" -and [string]::IsNullOrWhiteSpace($env:N8N_API_KEY)) {
            throw "awaiting_n8n_operator_setup: complete the documented n8n owner/API-key setup before -Run."
        }
        Assert-RequiredEnvironment -Names @("N8N_API_KEY", "N8N_KAFKA_CREDENTIAL_DATA_JSON", "RECLAIM_N8N_SERVICE_TOKEN")
        $composeArgs = Get-ComposeArguments -Name $ProjectName
        $volumeProof = Get-VolumeProof -Name $ProjectName -ArtifactPath (Join-Path $runDirectory "run-postgres-volume-proof.txt")
        $ps = Invoke-Compose -Arguments ($composeArgs + @("ps") + $t153ServiceInventory) -ArtifactPath (Join-Path $runDirectory "run-container-health.txt") -PersistOutput
        Assert-CommandSucceeded -Result $ps -Description "existing T153 project health check"
        $bootstrapPath = Join-Path $repositoryRoot "infra\n8n\bootstrap.ps1"
        $bootstrap = Invoke-RecordedCommand -FilePath "pwsh" -Arguments @("-NoProfile", "-File", $bootstrapPath, "-N8nBaseUrl", $record.ports.n8n, "-Activate") -ArtifactPath (Join-Path $runDirectory "n8n-bootstrap.txt") -PersistOutput
        Assert-CommandSucceeded -Result $bootstrap -Description "n8n workflow bootstrap and activation"
        $gateResults = Invoke-RunGates -Record $record -ArtifactDirectory $runDirectory
        $record.state = "run_complete"
        $record.run_finished_at_utc = (Get-Date -AsUTC).ToString("o")
        $record.postgres_volume = $volumeProof
        $record.test_exit_codes = $gateResults
        $record.sanitized_summary = $true
        Save-ProjectRecord -Record $record
        Write-Host "T153 run complete project=$ProjectName run_id=$($record.run_id)"
        return $record
    } catch {
        $safeMessage = Redact-Text $_.Exception.Message
        Save-FailedProjectRecord -Name $ProjectName -FailureMessage $safeMessage -ExitCode 1
        throw
    }
}

function Cleanup-T153 {
    $composeArgs = Get-ComposeArguments -Name $ProjectName
    $volumeKeys = @("postgres-data", "redpanda-data", "redis-data", "minio-data")
    $namedVolumes = @($volumeKeys | ForEach-Object { Get-NamedVolume -Name $ProjectName -Key $_ })
    Write-Host "Cleanup project=$ProjectName named volumes=$($namedVolumes -join ', ')"
    # Only explicit -Cleanup may call docker compose down --volumes.
    $down = Invoke-Compose -Arguments ($composeArgs + @("down", "--volumes", "--remove-orphans")) -ArtifactPath (Join-Path $t153Root ("{0}-cleanup.txt" -f $ProjectName)) -PersistOutput
    Assert-CommandSucceeded -Result $down -Description "T153 cleanup"
    Write-Host "Removed project=$ProjectName named volumes=$($namedVolumes -join ', ')"
}

if (-not $DefineOnly) {
    try {
        Assert-ExactlyOneMode
        Assert-SafeProjectName -Name $ProjectName
        if ($Prepare) {
            Prepare-T153
        } elseif ($Run) {
            Run-T153
        } elseif ($Cleanup) {
            Cleanup-T153
        }
    } catch {
        $safeMessage = Redact-Text $_.Exception.Message
        if ($Run) {
            Save-FailedProjectRecord -Name $ProjectName -FailureMessage $safeMessage -ExitCode 1
        }
        Write-Error $safeMessage
        exit 1
    }
}
