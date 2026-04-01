[CmdletBinding()]
param(
    [ValidateSet("runtime", "full")]
    [string]$ComposeMode = "runtime",

    [string[]]$ChangedPaths = @(),

    [string]$DockerPythonExtras = "",

    [switch]$NoBuild,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$lockDir = Join-Path $repoRoot "logs"
$lockPath = Join-Path $lockDir ("docker-refresh-{0}.lock" -f $ComposeMode)
$codexHostBridgeEnvPath = Join-Path $lockDir "codex-host-bridge.env"

function Get-RoughCutLockRecord {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $null
    }

    $record = [ordered]@{}
    foreach ($line in (Get-Content $Path -ErrorAction SilentlyContinue)) {
        if ($line -match "^\s*([^=]+?)=(.*)$") {
            $record[$Matches[1]] = $Matches[2]
        }
    }

    if ($record.Count -eq 0) {
        return $null
    }

    return [pscustomobject]$record
}

function Format-RoughCutLockRecord {
    param($LockRecord)

    if ($null -eq $LockRecord) {
        return "<empty>"
    }

    $pairs = @()
    foreach ($prop in $LockRecord.PSObject.Properties) {
        $pairs += ("{0}={1}" -f $prop.Name, $prop.Value)
    }

    return ($pairs -join ", ")
}

function Test-RoughCutProcessActive {
    param(
        [int]$ProcessId,
        [string]$ScriptName
    )

    if ($ProcessId -le 0) {
        return $false
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }

    $commandLine = [string]($process.CommandLine ?? "")
    return $commandLine -match [regex]::Escape($ScriptName)
}

function Resolve-RefreshLockState {
    param(
        [string]$Path,
        [string]$ScriptName
    )

    if (-not (Test-Path $Path)) {
        return
    }

    $lockRecord = Get-RoughCutLockRecord -Path $Path
    $lockPid = $null
    if ($null -ne $lockRecord -and $null -ne $lockRecord.pid -and $lockRecord.pid -match "^\d+$") {
        $lockPid = [int]$lockRecord.pid
    }

    if ($null -ne $lockPid -and (Test-RoughCutProcessActive -ProcessId $lockPid -ScriptName $ScriptName)) {
        throw "RoughCut docker refresh session is already running for $ComposeMode. Lock: $Path`n$(Format-RoughCutLockRecord -LockRecord $lockRecord)"
    }

    Write-Warning ("Removing stale RoughCut docker refresh lock for {0}: {1}" -f $ComposeMode, (Format-RoughCutLockRecord -LockRecord $lockRecord))
    Remove-Item $Path -Force -ErrorAction SilentlyContinue
}

function Get-RoughCutRefreshGateState {
    param(
        [string[]]$ComposeArgs
    )

    $probeSql = @"
SELECT
  COALESCE((SELECT COUNT(*) FROM jobs WHERE status = 'processing'), 0) AS active_jobs,
  COALESCE((SELECT COUNT(*) FROM job_steps WHERE status = 'running'), 0) AS running_steps;
"@

    $probeOutput = @(
        & docker @ComposeArgs exec -T postgres psql -U roughcut -d roughcut -v ON_ERROR_STOP=1 -tA -F "|" -c $probeSql 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        $detail = if ($probeOutput.Count -gt 0) { ($probeOutput -join [Environment]::NewLine) } else { "unknown error" }
        throw "Failed to probe active work before refresh for ${ComposeMode}: $detail"
    }

    $payloadLine = @($probeOutput | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1)
    if ([string]::IsNullOrWhiteSpace($payloadLine)) {
        throw "Failed to parse active work probe output before refresh for ${ComposeMode}."
    }

    $fields = $payloadLine -split "\|"
    if ($fields.Count -lt 2) {
        throw "Unexpected active work probe output before refresh for ${ComposeMode}: $payloadLine"
    }

    return [pscustomobject]@{
        active_jobs = [int]$fields[0]
        running_steps = [int]$fields[1]
    }
}

function Invoke-Step {
    param([string]$Message, [scriptblock]$ActionBlock)

    Write-Host $Message
    if (-not $DryRun) {
        & $ActionBlock
    }
}

function Get-RoughCutComposeFiles {
    param(
        [ValidateSet("runtime", "full")]
        [string]$Mode
    )

    $files = @(
        "docker-compose.infra.yml",
        "docker-compose.runtime.yml"
    )
    if ($Mode -eq "full") {
        $files += "docker-compose.automation.yml"
    }
    return $files
}

function Get-RoughCutRefreshServices {
    param(
        [ValidateSet("runtime", "full")]
        [string]$Mode
    )

    $services = @(
        "migrate",
        "api",
        "orchestrator",
        "worker-media",
        "worker-llm"
    )
    if ($Mode -eq "full") {
        $services += "watcher"
    }
    return $services
}

function Import-CodexHostBridgeEnv {
    param([string]$Path)

    $previousValues = @{}
    foreach ($name in @("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", "ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN")) {
        $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    if (-not (Test-Path $Path)) {
        return $previousValues
    }

    foreach ($line in (Get-Content $Path -ErrorAction SilentlyContinue)) {
        if ($line -match "^\s*([^=]+?)=(.*)$") {
            $name = $Matches[1]
            $value = $Matches[2]
            if ($name -in @("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", "ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN")) {
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
            }
        }
    }

    return $previousValues
}

function Restore-CodexHostBridgeEnv {
    param([hashtable]$PreviousValues)

    if ($null -eq $PreviousValues) {
        return
    }

    foreach ($entry in $PreviousValues.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
}

New-Item -ItemType Directory -Force -Path $lockDir | Out-Null

Resolve-RefreshLockState -Path $lockPath -ScriptName "run-roughcut-docker-refresh-session.ps1"

$lockContent = @(
    "pid=$PID"
    "started_at_utc=$([DateTime]::UtcNow.ToString("o"))"
    "compose_mode=$ComposeMode"
    "script=run-roughcut-docker-refresh-session.ps1"
    "workspace_root=$repoRoot"
) -join [Environment]::NewLine
Set-Content -Path $lockPath -Value $lockContent -Encoding UTF8

try {
    Set-Location $repoRoot
    $previousCodexBridgeEnv = Import-CodexHostBridgeEnv -Path $codexHostBridgeEnvPath

    if ($ChangedPaths.Count -gt 0) {
        Write-Host "Changed paths:"
        foreach ($path in ($ChangedPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
            Write-Host (" - {0}" -f $path)
        }
    }

    $composeArgs = @("compose")
    foreach ($composeFile in (Get-RoughCutComposeFiles -Mode $ComposeMode)) {
        $composePath = Join-Path $repoRoot $composeFile
        if (-not (Test-Path $composePath)) {
            throw "Compose file not found: $composePath"
        }
        $composeArgs += "-f"
        $composeArgs += $composeFile
    }

    $refreshGate = Get-RoughCutRefreshGateState -ComposeArgs $composeArgs
    if ($refreshGate.active_jobs -gt 0 -or $refreshGate.running_steps -gt 0) {
        $detail = "active_jobs=$($refreshGate.active_jobs), running_steps=$($refreshGate.running_steps)"
        Write-Warning ("Deferring Docker refresh for {0} because active work is still running: {1}" -f $ComposeMode, $detail)
        throw "[DEFERRED] $detail"
    }

    $upArgs = @("up", "-d")
    if (-not $NoBuild) {
        $upArgs += "--build"
    }
    $upArgs += "--force-recreate"
    $upArgs += "--remove-orphans"
    $upArgs += Get-RoughCutRefreshServices -Mode $ComposeMode

    $previousDockerExtras = [Environment]::GetEnvironmentVariable("ROUGHCUT_DOCKER_PYTHON_EXTRAS", "Process")
    $extrasLabel = if ([string]::IsNullOrWhiteSpace($DockerPythonExtras)) { "<none>" } else { $DockerPythonExtras }
    try {
        [Environment]::SetEnvironmentVariable("ROUGHCUT_DOCKER_PYTHON_EXTRAS", $DockerPythonExtras, "Process")
        Invoke-Step ("Refresh Docker {0} runtime via docker compose {1} (python extras: {2})" -f $ComposeMode, ($upArgs -join " "), $extrasLabel) {
            docker @composeArgs @upArgs
            if ($LASTEXITCODE -ne 0) {
                throw "docker compose refresh failed for $ComposeMode with exit code $LASTEXITCODE"
            }
        }
    } finally {
        [Environment]::SetEnvironmentVariable("ROUGHCUT_DOCKER_PYTHON_EXTRAS", $previousDockerExtras, "Process")
    }
    Write-Host ("Docker refresh session completed successfully for {0}." -f $ComposeMode)
} catch {
    $failureMessage = $_.Exception.Message
    if ($_.Exception.InnerException) {
        $failureMessage = "{0}`nInner exception: {1}" -f $failureMessage, $_.Exception.InnerException.Message
    }
    Write-Error ("RoughCut docker refresh session failed for {0}: {1}" -f $ComposeMode, $failureMessage)
    throw
} finally {
    Restore-CodexHostBridgeEnv -PreviousValues $previousCodexBridgeEnv
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
}
