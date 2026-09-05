[CmdletBinding()]
param(
    [string]$N8nBaseUrl = $(if ($env:RECLAIM_N8N_API_BASE_URL) { $env:RECLAIM_N8N_API_BASE_URL } else { $env:RECLAIM_N8N_BASE_URL }),
    [string]$ApiKey = $env:N8N_API_KEY,
    [string]$ServiceToken = $env:RECLAIM_N8N_SERVICE_TOKEN,
    [string]$CredentialRevision = $(if ($env:RECLAIM_N8N_CREDENTIAL_REVISION) { $env:RECLAIM_N8N_CREDENTIAL_REVISION } else { "v1" }),
    [switch]$Rotate,
    [switch]$Activate
)

$ErrorActionPreference = "Stop"
$workflowDirectory = Join-Path $PSScriptRoot "workflows"

function Assert-RequiredValue([string]$Value, [string]$Message) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw $Message
    }
}

function Assert-ActivationPrerequisite([string]$EnvironmentVariable) {
    $value = [Environment]::GetEnvironmentVariable($EnvironmentVariable)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$EnvironmentVariable is required when -Activate is supplied."
    }
}

function Assert-SafeCredentialRevision([string]$Revision) {
    if ([string]::IsNullOrWhiteSpace($Revision) -or $Revision -notmatch '^[A-Za-z0-9._-]+$') {
        throw "RECLAIM_N8N_CREDENTIAL_REVISION must be a non-empty safe revision identifier."
    }
}

function Get-ManagedCredentialName([string]$BaseName, [string]$Revision, [bool]$ShouldRotate) {
    if ($ShouldRotate) {
        return "$BaseName.$Revision"
    }
    return $BaseName
}

function Read-JsonHashtable([string]$Text, [string]$SourceName) {
    try {
        return $Text | ConvertFrom-Json -AsHashtable
    } catch {
        throw "$SourceName must be valid JSON."
    }
}

function Normalize-KafkaCredentialData([hashtable]$Data) {
    $normalized = @{}
    foreach ($key in $Data.Keys) {
        $normalized[$key] = $Data[$key]
    }
    if ($normalized.ContainsKey("brokers") -and $normalized.brokers -isnot [string]) {
        $normalized.brokers = @($normalized.brokers | ForEach-Object { [string]$_ }) -join ","
    }
    if (-not $normalized.ContainsKey("authentication")) {
        $normalized.authentication = $false
    }
    return $normalized
}

function Get-PaginatedData([string]$Path) {
    $items = [System.Collections.ArrayList]::new()
    $cursor = $null
    do {
        $queryParameters = [System.Collections.ArrayList]::new()
        [void]$queryParameters.Add("limit=250")
        if (-not [string]::IsNullOrWhiteSpace($cursor)) {
            [void]$queryParameters.Add("cursor=$([uri]::EscapeDataString($cursor))")
        }
        $uri = "{0}{1}?{2}" -f $apiRoot, $Path, ($queryParameters -join '&')
        $response = Invoke-RestMethod -Method Get -Uri $uri -Headers $headers
        foreach ($item in @($response.data)) {
            [void]$items.Add($item)
        }
        $cursor = $response.nextCursor
    } while (-not [string]::IsNullOrWhiteSpace($cursor))
    return @($items)
}

function Get-CredentialReference([object[]]$Workflows, [string]$Type, [string]$Name) {
    foreach ($workflow in @($Workflows)) {
        foreach ($node in @($workflow.nodes)) {
            if ($null -eq $node -or $null -eq $node.credentials) {
                continue
            }
            $credential = $null
            if ($node.credentials -is [hashtable]) {
                $credential = $node.credentials[$Type]
            } else {
                $credential = $node.credentials.$Type
            }
            if ($null -eq $credential) {
                continue
            }
            if ([string]$credential.name -eq $Name -and
                -not [string]::IsNullOrWhiteSpace([string]$credential.id) -and
                [string]$credential.id -notmatch '^__') {
                return [ordered]@{
                    id = [string]$credential.id
                    name = $Name
                    type = $Type
                }
            }
        }
    }
    return $null
}

function Ensure-Credential([string]$Name, [string]$Type, [object]$Data, [object[]]$ExistingWorkflows) {
    $existingCredential = Get-CredentialReference -Workflows $ExistingWorkflows -Type $Type -Name $Name
    if ($null -ne $existingCredential) {
        # n8n 1.121's public API intentionally exposes credential creation but
        # not credential listing/update. Reuse the ID already referenced by a
        # managed workflow so reruns remain idempotent without unsupported GETs.
        return $existingCredential
    }
    $payload = @{ name = $Name; type = $Type; data = $Data } | ConvertTo-Json -Depth 20
    return Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/credentials" -Headers $headers -ContentType "application/json" -Body $payload
}

function Assert-WorkflowCredentialReference([hashtable]$Workflow, [string]$Type, [string]$Name, [string]$Id) {
    $references = @(
        foreach ($node in @($Workflow.nodes)) {
            if ($null -eq $node -or $null -eq $node.credentials) { continue }
            $reference = if ($node.credentials -is [hashtable]) { $node.credentials[$Type] } else { $node.credentials.$Type }
            if ($null -ne $reference) { $reference }
        }
    )
    if ($references.Count -eq 0 -or @($references | Where-Object { [string]$_.id -ne $Id -or [string]$_.name -ne $Name }).Count -gt 0) {
        throw "managed workflow $($Workflow.name) does not reference credential $Name"
    }
}

function Get-Workflow([object[]]$Workflows, [string]$Name) {
    return @($Workflows | Where-Object { $_.name -eq $Name }) | Select-Object -First 1
}

function Prepare-Workflow([string]$Path, [string]$HttpCredentialId, [string]$KafkaCredentialId, [string]$ErrorWorkflowId) {
    $workflow = Read-JsonHashtable -Text (Get-Content -Raw -LiteralPath $Path) -SourceName $Path
    $writableFields = @("name", "nodes", "connections", "settings", "staticData")
    foreach ($key in @($workflow.Keys)) {
        if ($writableFields -notcontains $key) {
            $workflow.Remove($key)
        }
    }
    foreach ($node in @($workflow.nodes)) {
        if ($null -ne $node.credentials.httpHeaderAuth) {
            $node.credentials.httpHeaderAuth.id = $HttpCredentialId
        }
        if (-not [string]::IsNullOrWhiteSpace($KafkaCredentialId) -and $null -ne $node.credentials.kafka) {
            $node.credentials.kafka.id = $KafkaCredentialId
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ErrorWorkflowId) -and $workflow.name -eq "incident-analysis-handoff.v1") {
        $workflow.settings.errorWorkflow = $ErrorWorkflowId
    }
    return $workflow
}

function Upsert-Workflow([hashtable]$Workflow, [object[]]$ExistingWorkflows) {
    $payload = $Workflow | ConvertTo-Json -Depth 30
    $existing = Get-Workflow -Workflows $ExistingWorkflows -Name $Workflow.name
    if ($null -eq $existing) {
        return Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/workflows" -Headers $headers -ContentType "application/json" -Body $payload
    }
    return Invoke-RestMethod -Method Put -Uri "$apiRoot/api/v1/workflows/$($existing.id)" -Headers $headers -ContentType "application/json" -Body $payload
}

Assert-RequiredValue -Value $N8nBaseUrl -Message "RECLAIM_N8N_BASE_URL is required."
Assert-RequiredValue -Value $ApiKey -Message "N8N_API_KEY is required."
Assert-RequiredValue -Value $ServiceToken -Message "RECLAIM_N8N_SERVICE_TOKEN is required."
Assert-SafeCredentialRevision -Revision $CredentialRevision

if ($Activate) {
    foreach ($requiredEnvironmentVariable in @(
        "N8N_API_KEY",
        "N8N_KAFKA_CREDENTIAL_DATA_JSON",
        "RECLAIM_N8N_SERVICE_TOKEN"
    )) {
        Assert-ActivationPrerequisite -EnvironmentVariable $requiredEnvironmentVariable
    }
}

$headers = @{ "X-N8N-API-KEY" = $ApiKey; Accept = "application/json" }
$apiRoot = $N8nBaseUrl.TrimEnd('/')

$existingWorkflows = Get-PaginatedData -Path "/api/v1/workflows"

$httpCredentialName = if ($Rotate) { "reclaim-orchestrator-service.$CredentialRevision" } else { "reclaim-orchestrator-service" }
$kafkaCredentialName = if ($Rotate) { "reclaim-redpanda-readonly.$CredentialRevision" } else { "reclaim-redpanda-readonly" }
$httpCredential = Ensure-Credential $httpCredentialName "httpHeaderAuth" @{
    name = "Authorization"
    value = "Bearer $ServiceToken"
} -ExistingWorkflows $existingWorkflows

$kafkaCredential = $null
if (-not [string]::IsNullOrWhiteSpace($env:N8N_KAFKA_CREDENTIAL_DATA_JSON)) {
    $kafkaData = Normalize-KafkaCredentialData -Data (Read-JsonHashtable -Text $env:N8N_KAFKA_CREDENTIAL_DATA_JSON -SourceName "N8N_KAFKA_CREDENTIAL_DATA_JSON")
    $kafkaCredential = Ensure-Credential $kafkaCredentialName "kafka" $kafkaData -ExistingWorkflows $existingWorkflows
} elseif ($Activate) {
    throw "N8N_KAFKA_CREDENTIAL_DATA_JSON is required when -Activate is supplied."
} else {
    Write-Warning "N8N_KAFKA_CREDENTIAL_DATA_JSON is not set; Kafka credential remains a checked-in placeholder."
}

$recoveryWorkflow = Prepare-Workflow -Path (Join-Path $workflowDirectory "incident-analysis-error-recovery.v1.json") -HttpCredentialId $httpCredential.id -KafkaCredentialId $null -ErrorWorkflowId $null
Assert-WorkflowCredentialReference -Workflow $recoveryWorkflow -Type "httpHeaderAuth" -Name $httpCredentialName -Id $httpCredential.id
$recoveryResult = Upsert-Workflow -Workflow $recoveryWorkflow -ExistingWorkflows $existingWorkflows
Write-Host "Upserted incident-analysis-error-recovery.v1"

$existingWorkflows = Get-PaginatedData -Path "/api/v1/workflows"
$handoffWorkflow = Prepare-Workflow -Path (Join-Path $workflowDirectory "incident-analysis-handoff.v1.json") -HttpCredentialId $httpCredential.id -KafkaCredentialId $kafkaCredential.id -ErrorWorkflowId $recoveryResult.id
Assert-WorkflowCredentialReference -Workflow $handoffWorkflow -Type "httpHeaderAuth" -Name $httpCredentialName -Id $httpCredential.id
if ($null -ne $kafkaCredential) {
    Assert-WorkflowCredentialReference -Workflow $handoffWorkflow -Type "kafka" -Name $kafkaCredentialName -Id $kafkaCredential.id
}
$handoffResult = Upsert-Workflow -Workflow $handoffWorkflow -ExistingWorkflows $existingWorkflows
Write-Host "Upserted incident-analysis-handoff.v1"

if ($Activate) {
    Invoke-RestMethod -Method Post -Uri "$apiRoot/api/v1/workflows/$($handoffResult.id)/activate" -Headers $headers | Out-Null
    $verifiedWorkflow = Invoke-RestMethod -Method Get -Uri "$apiRoot/api/v1/workflows/$($handoffResult.id)" -Headers $headers
    if (-not $verifiedWorkflow.active) {
        throw "Handoff workflow activation could not be verified."
    }
    Write-Host "Activated incident-analysis-handoff.v1 and verified active state."
} else {
    Write-Host "n8n workflow bootstrap completed. Workflows remain inactive pending operator verification."
}
