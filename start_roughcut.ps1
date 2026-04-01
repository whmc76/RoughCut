param(
    [ValidateSet("local", "infra", "runtime", "full", "runtime-watch", "full-watch", "runtime-down", "full-down")]
    [string]$Mode = "local",
    [string]$DockerPythonExtras = "",
    [int]$Port = 38471,
    [switch]$SkipDocker,
    [switch]$SkipMigrate,
    [switch]$CleanupLegacyDocker,
    [switch]$StopOnly,
    [switch]$StopDocker,
    [switch]$NoPause,
    [switch]$NoWatcher,
    [switch]$NoDockerWatch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Uv = Get-Command uv -ErrorAction SilentlyContinue
$SystemPython = Get-Command python -ErrorAction SilentlyContinue
$Pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
$FrontendDir = Join-Path $RepoRoot "frontend"
$FrontendSrcDir = Join-Path $FrontendDir "src"
$FrontendDist = Join-Path $FrontendDir "dist\index.html"
$WatchDir = Join-Path $RepoRoot "watch"
$InfraComposeFile = Join-Path $RepoRoot "docker-compose.infra.yml"
$RuntimeComposeFile = Join-Path $RepoRoot "docker-compose.runtime.yml"
$AutomationComposeFile = Join-Path $RepoRoot "docker-compose.automation.yml"
$DockerWatchScript = Join-Path $RepoRoot "scripts\watch-roughcut-docker-runtime.ps1"
$CodexHostBridgeScript = Join-Path $RepoRoot "scripts\codex_host_bridge.py"
$CodexHostBridgeEnvFile = Join-Path $RepoRoot "logs\codex-host-bridge.env"
$CodexHostBridgeOutLog = Join-Path $RepoRoot "logs\codex-host-bridge.out.log"
$CodexHostBridgeErrLog = Join-Path $RepoRoot "logs\codex-host-bridge.err.log"
$CodexHostBridgePort = 38695
$CodexHostBridgeBindHost = "0.0.0.0"
$script:ManagedProcesses = @()

function Invoke-NativeCommandChecked {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$FailureMessage
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        if ($FailureMessage) {
            throw "$FailureMessage (exit code $LASTEXITCODE)."
        }
        throw "Command failed: $FilePath $($Arguments -join ' ') (exit code $LASTEXITCODE)."
    }
}

function Get-RoughCutComposeFiles {
    param(
        [ValidateSet("infra", "runtime", "full")]
        [string]$ComposeMode
    )

    $files = @($InfraComposeFile)
    if ($ComposeMode -in @("runtime", "full")) {
        $files += $RuntimeComposeFile
    }
    if ($ComposeMode -eq "full") {
        $files += $AutomationComposeFile
    }
    return $files
}

function Invoke-RoughCutCompose {
    param(
        [ValidateSet("infra", "runtime", "full")]
        [string]$ComposeMode,
        [string[]]$ComposeArguments,
        [string]$DockerPythonExtrasOverride = ""
    )

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $docker) {
        throw "Docker Desktop is required for mode '$ComposeMode'."
    }

    $composeFiles = Get-RoughCutComposeFiles -ComposeMode $ComposeMode
    $args = @("compose")
    foreach ($composeFile in $composeFiles) {
        if (-not (Test-Path $composeFile)) {
            throw "Compose file not found: $composeFile"
        }
        $args += "-f"
        $args += $composeFile
    }
    $args += $ComposeArguments
    $previousDockerExtras = [Environment]::GetEnvironmentVariable("ROUGHCUT_DOCKER_PYTHON_EXTRAS", "Process")
    try {
        if ($ComposeMode -in @("runtime", "full")) {
            [Environment]::SetEnvironmentVariable("ROUGHCUT_DOCKER_PYTHON_EXTRAS", $DockerPythonExtrasOverride, "Process")
        }
        Invoke-NativeCommandChecked -FilePath $docker.Source -Arguments $args -FailureMessage "docker compose command failed"
    } finally {
        [Environment]::SetEnvironmentVariable("ROUGHCUT_DOCKER_PYTHON_EXTRAS", $previousDockerExtras, "Process")
    }
}

function Get-RoughCutComposeStatusEntries {
    param(
        [ValidateSet("infra", "runtime", "full")]
        [string]$ComposeMode
    )

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $docker) {
        throw "Docker Desktop is required for mode '$ComposeMode'."
    }

    $composeFiles = Get-RoughCutComposeFiles -ComposeMode $ComposeMode
    $args = @("compose")
    foreach ($composeFile in $composeFiles) {
        $args += "-f"
        $args += $composeFile
    }
    $args += @("ps", "--all", "--format", "json")

    $rawOutput = & $docker.Source @args
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect docker compose status for mode '$ComposeMode' (exit code $LASTEXITCODE)."
    }

    $entries = @()
    foreach ($line in ($rawOutput -split "(`r`n|`n|`r)")) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        $entries += $trimmed | ConvertFrom-Json
    }

    return $entries
}

function Wait-RoughCutComposeModeReady {
    param(
        [ValidateSet("runtime", "full")]
        [string]$ComposeMode,
        [int]$TimeoutSec = 120
    )

    $requiredRunningServices = @("postgres", "redis", "minio", "api", "orchestrator", "worker-media", "worker-llm")
    if ($ComposeMode -eq "full") {
        $requiredRunningServices += "watcher"
    }

    $requiredHealthyServices = @("postgres", "redis", "minio")
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $lastIssues = @()

    while ((Get-Date) -lt $deadline) {
        $entries = @(Get-RoughCutComposeStatusEntries -ComposeMode $ComposeMode)
        $serviceMap = @{}
        foreach ($entry in $entries) {
            $serviceMap[[string]$entry.Service] = $entry
        }

        $issues = @()
        foreach ($serviceName in $requiredRunningServices) {
            if (-not $serviceMap.ContainsKey($serviceName)) {
                $issues += "$serviceName missing"
                continue
            }

            $entry = $serviceMap[$serviceName]
            if ($entry.State -ne "running") {
                $exitCode = if ($null -ne $entry.ExitCode -and "$($entry.ExitCode)" -ne "") { " exit=$($entry.ExitCode)" } else { "" }
                $issues += "$serviceName state=$($entry.State)$exitCode"
                continue
            }

            if ($serviceName -in $requiredHealthyServices -and $entry.Health -and $entry.Health -ne "healthy") {
                $issues += "$serviceName health=$($entry.Health)"
            }
        }

        if (-not $serviceMap.ContainsKey("migrate")) {
            $issues += "migrate missing"
        } else {
            $migrateEntry = $serviceMap["migrate"]
            if ($migrateEntry.State -ne "exited" -or $migrateEntry.ExitCode -ne 0) {
                $issues += "migrate state=$($migrateEntry.State) exit=$($migrateEntry.ExitCode)"
            }
        }

        if ($issues.Count -eq 0) {
            return
        }

        $lastIssues = $issues
        Start-Sleep -Seconds 2
    }

    $detail = if ($lastIssues.Count -gt 0) { $lastIssues -join "; " } else { "unknown status" }
    throw "Docker mode '$ComposeMode' did not become ready within $TimeoutSec seconds: $detail"
}

function Start-RoughCutComposeMode {
    param(
        [ValidateSet("infra", "runtime", "full")]
        [string]$ComposeMode
    )

    Write-Host "Starting RoughCut Docker mode: $ComposeMode" -ForegroundColor Cyan
    if ($ComposeMode -in @("runtime", "full")) {
        Start-RoughCutCodexHostBridge
    }
    switch ($ComposeMode) {
        "infra" {
            Invoke-RoughCutCompose -ComposeMode $ComposeMode -ComposeArguments @("up", "-d", "--remove-orphans")
        }
        default {
            try {
                Invoke-RoughCutCompose -ComposeMode $ComposeMode -ComposeArguments @("up", "-d", "--build", "--remove-orphans") -DockerPythonExtrasOverride $DockerPythonExtras
            } catch {
                $existingImage = docker image inspect roughcut:local 2>$null
                if ($LASTEXITCODE -ne 0) {
                    throw
                }
                Write-Host "Docker build failed, but local image roughcut:local exists. Retrying without --build." -ForegroundColor Yellow
                Invoke-RoughCutCompose -ComposeMode $ComposeMode -ComposeArguments @("up", "-d", "--remove-orphans") -DockerPythonExtrasOverride $DockerPythonExtras
            }
        }
    }

    if ($ComposeMode -in @("runtime", "full")) {
        Write-Host "Verifying RoughCut Docker mode: $ComposeMode" -ForegroundColor Cyan
        Wait-RoughCutComposeModeReady -ComposeMode $ComposeMode
    }

    Write-Host ""
    switch ($ComposeMode) {
        "infra" {
            Write-Host "Infra services are up." -ForegroundColor Green
        }
        "runtime" {
            Write-Host "Recommended always-on runtime is up." -ForegroundColor Green
        }
        "full" {
            Write-Host "Runtime plus automation services are up." -ForegroundColor Green
        }
    }
}

function Stop-RoughCutComposeMode {
    param(
        [ValidateSet("runtime", "full")]
        [string]$ComposeMode
    )

    Stop-RoughCutDockerWatch -ComposeMode $ComposeMode
    Stop-RoughCutCodexHostBridge -SilentlyContinue
    Write-Host "Stopping RoughCut Docker mode: $ComposeMode" -ForegroundColor Cyan
    Invoke-RoughCutCompose -ComposeMode $ComposeMode -ComposeArguments @("down", "--remove-orphans")
}

function Get-RoughCutDockerWatchLockPath {
    param(
        [ValidateSet("runtime", "full")]
        [string]$ComposeMode
    )

    return Join-Path $RepoRoot ("logs\docker-watch-{0}.lock" -f $ComposeMode)
}

function Get-RoughCutDockerWatchProcessId {
    param([string]$LockPath)

    if (-not (Test-Path $LockPath)) {
        return $null
    }

    foreach ($line in (Get-Content $LockPath -ErrorAction SilentlyContinue)) {
        if ($line -match "^pid=(\d+)$") {
            return [int]$Matches[1]
        }
    }

    return $null
}

function Test-RoughCutDockerWatchActive {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return $false
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }

    $commandLine = [string]($process.CommandLine ?? "")
    return $commandLine -match [regex]::Escape("watch-roughcut-docker-runtime.ps1")
}

function Get-PowerShellCommand {
    $powerShellCommand = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($null -eq $powerShellCommand) {
        $powerShellCommand = Get-Command powershell -ErrorAction SilentlyContinue
    }
    if ($null -eq $powerShellCommand) {
        throw "PowerShell executable not found."
    }
    return $powerShellCommand
}

function Get-RoughCutCodexHostBridgeToken {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-RoughCutCodexHostBridgeProcessMatchPattern {
    return [regex]::Escape("scripts\codex_host_bridge.py")
}

function Test-RoughCutCodexHostBridgeActive {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return $false
    }

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }

    $commandLine = [string]($process.CommandLine ?? "")
    return $commandLine -match (Get-RoughCutCodexHostBridgeProcessMatchPattern)
}

function Test-RoughCutCodexHostBridgeReady {
    param([int]$TimeoutSec = 20)

    $uri = "http://127.0.0.1:$CodexHostBridgePort/healthz"
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $uri -Method Get -TimeoutSec 3
            if ($response.status -eq "ok") {
                return $true
            }
        } catch {
        }
        Start-Sleep -Milliseconds 400
    }
    return $false
}

function Get-RoughCutCodexHostBridgeEnvMap {
    param([string]$Token)

    return [ordered]@{
        ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL = "http://host.docker.internal:$CodexHostBridgePort/v1/codex/exec"
        ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN = $Token
    }
}

function Write-RoughCutCodexHostBridgeEnvFile {
    param([System.Collections.IDictionary]$EnvironmentMap)

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CodexHostBridgeEnvFile) | Out-Null
    $lines = @()
    foreach ($entry in $EnvironmentMap.GetEnumerator()) {
        $lines += ("{0}={1}" -f $entry.Key, $entry.Value)
    }
    Set-Content -Path $CodexHostBridgeEnvFile -Value $lines -Encoding UTF8
}

function Read-RoughCutCodexHostBridgeEnvFile {
    if (-not (Test-Path $CodexHostBridgeEnvFile)) {
        return @{}
    }

    $environmentMap = @{}
    foreach ($line in (Get-Content $CodexHostBridgeEnvFile -ErrorAction SilentlyContinue)) {
        if ($line -match "^\s*([^=]+?)=(.*)$") {
            $environmentMap[$Matches[1]] = $Matches[2]
        }
    }

    return $environmentMap
}

function Set-RoughCutCodexHostBridgeEnv {
    param([string]$Token)

    $environmentMap = Get-RoughCutCodexHostBridgeEnvMap -Token $Token
    Write-RoughCutCodexHostBridgeEnvFile -EnvironmentMap $environmentMap
    foreach ($entry in $environmentMap.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
}

function Import-RoughCutCodexHostBridgeEnv {
    $environmentMap = Read-RoughCutCodexHostBridgeEnvFile
    foreach ($entry in $environmentMap.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
    return $environmentMap
}

function Clear-RoughCutCodexHostBridgeEnv {
    foreach ($name in @("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", "ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN")) {
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    if (Test-Path $CodexHostBridgeEnvFile) {
        Remove-Item $CodexHostBridgeEnvFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-RoughCutCodexHostBridgeProcessId {
    $environmentMap = Read-RoughCutCodexHostBridgeEnvFile
    $rawValue = $environmentMap["pid"]
    if ($rawValue -and $rawValue -match "^\d+$") {
        return [int]$rawValue
    }
    return $null
}

function Get-RoughCutCodexHostBridgeLauncher {
    if (Test-Path $Python) {
        return [pscustomobject]@{
            FilePath = $Python
            Arguments = @($CodexHostBridgeScript)
        }
    }

    if ($null -ne $Uv) {
        return [pscustomobject]@{
            FilePath = $Uv.Source
            Arguments = @("run", "python", $CodexHostBridgeScript)
        }
    }

    if ($null -ne $SystemPython) {
        return [pscustomobject]@{
            FilePath = $SystemPython.Source
            Arguments = @($CodexHostBridgeScript)
        }
    }

    throw "Python executable not found for Codex host bridge."
}

function Start-RoughCutCodexHostBridge {
    if (-not (Test-Path $CodexHostBridgeScript)) {
        Write-Host "Codex host bridge script not found. ACP will stay on container-local auth." -ForegroundColor Yellow
        Clear-RoughCutCodexHostBridgeEnv
        return
    }

    $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
    $codexAuthPath = Join-Path $env:USERPROFILE ".codex\auth.json"
    if ($null -eq $codexCommand -or -not (Test-Path $codexAuthPath)) {
        Write-Host "Host Codex CLI or auth state is unavailable. ACP will stay on container-local auth." -ForegroundColor Yellow
        Clear-RoughCutCodexHostBridgeEnv
        return
    }

    $existingPid = Get-RoughCutCodexHostBridgeProcessId
    if ($null -ne $existingPid -and (Test-RoughCutCodexHostBridgeActive -ProcessId $existingPid) -and (Test-RoughCutCodexHostBridgeReady -TimeoutSec 2)) {
        Import-RoughCutCodexHostBridgeEnv | Out-Null
        Write-Host "Codex host bridge already running (PID $existingPid)." -ForegroundColor Green
        return
    }

    Stop-RoughCutCodexHostBridge -SilentlyContinue

    $token = Get-RoughCutCodexHostBridgeToken
    Set-RoughCutCodexHostBridgeEnv -Token $token

    New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "logs") | Out-Null
    Clear-Content -Path $CodexHostBridgeOutLog -ErrorAction SilentlyContinue
    Clear-Content -Path $CodexHostBridgeErrLog -ErrorAction SilentlyContinue

    $launcher = Get-RoughCutCodexHostBridgeLauncher
    $arguments = @()
    $arguments += $launcher.Arguments
    $arguments += @("--host", $CodexHostBridgeBindHost, "--port", "$CodexHostBridgePort", "--token", $token)

    $previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    try {
        if ($null -ne $SystemPython -and $launcher.FilePath -eq $SystemPython.Source) {
            $bridgePythonPath = Join-Path $RepoRoot "src"
            $nextPythonPath = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
                $bridgePythonPath
            } else {
                "$bridgePythonPath;$previousPythonPath"
            }
            [Environment]::SetEnvironmentVariable("PYTHONPATH", $nextPythonPath, "Process")
        }

        $process = Start-Process `
            -FilePath $launcher.FilePath `
            -ArgumentList $arguments `
            -WorkingDirectory $RepoRoot `
            -WindowStyle Hidden `
            -PassThru `
            -RedirectStandardOutput $CodexHostBridgeOutLog `
            -RedirectStandardError $CodexHostBridgeErrLog
    } finally {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $previousPythonPath, "Process")
    }

    $environmentMap = Read-RoughCutCodexHostBridgeEnvFile
    $environmentMap["pid"] = "$($process.Id)"
    Write-RoughCutCodexHostBridgeEnvFile -EnvironmentMap $environmentMap

    if (-not (Test-RoughCutCodexHostBridgeReady -TimeoutSec 20)) {
        $stderr = if (Test-Path $CodexHostBridgeErrLog) { (Get-Content $CodexHostBridgeErrLog -Raw -ErrorAction SilentlyContinue).Trim() } else { "" }
        $stdout = if (Test-Path $CodexHostBridgeOutLog) { (Get-Content $CodexHostBridgeOutLog -Raw -ErrorAction SilentlyContinue).Trim() } else { "" }
        Stop-RoughCutCodexHostBridge -SilentlyContinue
        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            throw "Codex host bridge failed to start: $stderr"
        }
        if (-not [string]::IsNullOrWhiteSpace($stdout)) {
            throw "Codex host bridge failed to start: $stdout"
        }
        throw "Codex host bridge failed to become ready."
    }

    Write-Host "Codex host bridge started on port $CodexHostBridgePort (PID $($process.Id))." -ForegroundColor Green
}

function Stop-RoughCutCodexHostBridge {
    param([switch]$SilentlyContinue)

    $processId = Get-RoughCutCodexHostBridgeProcessId
    if ($null -ne $processId -and (Test-RoughCutCodexHostBridgeActive -ProcessId $processId)) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            if (-not $SilentlyContinue) {
                Write-Host "Codex host bridge stopped (PID $processId)." -ForegroundColor Green
            }
        } catch {
            if (-not $SilentlyContinue) {
                Write-Host "Failed to stop Codex host bridge (PID $processId): $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
    } elseif (-not $SilentlyContinue) {
        Write-Host "Codex host bridge is not running." -ForegroundColor Yellow
    }

    Clear-RoughCutCodexHostBridgeEnv
}

function Get-RoughCutDockerWatchArguments {
    param(
        [ValidateSet("runtime", "full")]
        [string]$ComposeMode
    )

    $arguments = @("-NoProfile", "-File", $DockerWatchScript, "-ComposeMode", $ComposeMode)
    if (-not [string]::IsNullOrWhiteSpace($DockerPythonExtras)) {
        $arguments += @("-DockerPythonExtras", $DockerPythonExtras)
    }
    return $arguments
}

function Start-RoughCutDockerWatchMode {
    param(
        [ValidateSet("runtime-watch", "full-watch")]
        [string]$WatchMode
    )

    if (-not (Test-Path $DockerWatchScript)) {
        throw "Docker watch script not found: $DockerWatchScript"
    }

    $composeMode = if ($WatchMode -eq "full-watch") { "full" } else { "runtime" }
    $powerShellCommand = Get-PowerShellCommand
    Write-Host "Starting RoughCut Docker watch mode: $composeMode" -ForegroundColor Cyan
    Invoke-NativeCommandChecked -FilePath $powerShellCommand.Source -Arguments (Get-RoughCutDockerWatchArguments -ComposeMode $composeMode) -FailureMessage "Docker watch mode failed"
}

function Start-RoughCutDockerWatch {
    param(
        [ValidateSet("runtime", "full")]
        [string]$ComposeMode
    )

    if ($NoDockerWatch) {
        Write-Host "Docker watch disabled for mode $ComposeMode." -ForegroundColor Yellow
        return
    }

    if (-not (Test-Path $DockerWatchScript)) {
        throw "Docker watch script not found: $DockerWatchScript"
    }

    $otherMode = if ($ComposeMode -eq "full") { "runtime" } else { "full" }
    Stop-RoughCutDockerWatch -ComposeMode $otherMode -SilentlyContinue

    $lockPath = Get-RoughCutDockerWatchLockPath -ComposeMode $ComposeMode
    $existingPid = Get-RoughCutDockerWatchProcessId -LockPath $lockPath
    if ($null -ne $existingPid -and (Test-RoughCutDockerWatchActive -ProcessId $existingPid)) {
        Write-Host "Docker watch already running for $ComposeMode (PID $existingPid)." -ForegroundColor Yellow
        return
    }
    if (Test-Path $lockPath) {
        Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
    }

    $powerShellCommand = Get-PowerShellCommand
    $outLog = Join-Path $RepoRoot ("logs\docker-watch-{0}.out.log" -f $ComposeMode)
    $errLog = Join-Path $RepoRoot ("logs\docker-watch-{0}.err.log" -f $ComposeMode)
    New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "logs") | Out-Null

    Clear-Content -Path $outLog -ErrorAction SilentlyContinue
    Clear-Content -Path $errLog -ErrorAction SilentlyContinue

    $process = Start-Process `
        -FilePath $powerShellCommand.Source `
        -ArgumentList (Get-RoughCutDockerWatchArguments -ComposeMode $ComposeMode) `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog

    $confirmed = $false
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        Start-Sleep -Milliseconds 300
        if ($process.HasExited) {
            break
        }
        $activePid = Get-RoughCutDockerWatchProcessId -LockPath $lockPath
        if ($null -ne $activePid -and $activePid -eq $process.Id -and (Test-RoughCutDockerWatchActive -ProcessId $process.Id)) {
            $confirmed = $true
            break
        }
    }

    if (-not $confirmed) {
        $stderr = if (Test-Path $errLog) { (Get-Content $errLog -Raw -ErrorAction SilentlyContinue).Trim() } else { "" }
        $stdout = if (Test-Path $outLog) { (Get-Content $outLog -Raw -ErrorAction SilentlyContinue).Trim() } else { "" }
        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            throw "Docker watch failed to stay alive for ${ComposeMode}: $stderr"
        }
        if (-not [string]::IsNullOrWhiteSpace($stdout)) {
            throw "Docker watch failed to confirm startup for ${ComposeMode}: $stdout"
        }
        throw "Docker watch failed to confirm startup for $ComposeMode."
    }

    Write-Host "Docker watch started for $ComposeMode (PID $($process.Id))." -ForegroundColor Green
}

function Stop-RoughCutDockerWatch {
    param(
        [ValidateSet("runtime", "full", "all")]
        [string]$ComposeMode = "all",
        [switch]$SilentlyContinue
    )

    $modes = if ($ComposeMode -eq "all") { @("runtime", "full") } else { @($ComposeMode) }
    foreach ($modeName in $modes) {
        $lockPath = Get-RoughCutDockerWatchLockPath -ComposeMode $modeName
        $processId = Get-RoughCutDockerWatchProcessId -LockPath $lockPath
        if ($null -ne $processId -and (Test-RoughCutDockerWatchActive -ProcessId $processId)) {
            try {
                Stop-Process -Id $processId -Force -ErrorAction Stop
                Write-Host "Docker watch stopped for $modeName (PID $processId)." -ForegroundColor Green
            } catch {
                if (-not $SilentlyContinue) {
                    Write-Host "Failed to stop docker watch for $modeName (PID $processId): $($_.Exception.Message)" -ForegroundColor Yellow
                }
            }
        } elseif (-not $SilentlyContinue) {
            Write-Host "Docker watch is not running for $modeName." -ForegroundColor Yellow
        }

        if (Test-Path $lockPath) {
            Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
        }
    }
}

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class RoughCutJobObject
{
    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr hJob,
        int infoType,
        IntPtr lpJobObjectInfo,
        uint cbJobObjectInfoLength
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    public static IntPtr CreateKillOnCloseJob()
    {
        IntPtr handle = CreateJobObject(IntPtr.Zero, null);
        if (handle == IntPtr.Zero)
        {
            throw new InvalidOperationException("CreateJobObject failed.");
        }

        var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int length = Marshal.SizeOf<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>();
        IntPtr pointer = Marshal.AllocHGlobal(length);
        try
        {
            Marshal.StructureToPtr(info, pointer, false);
            if (!SetInformationJobObject(handle, JobObjectExtendedLimitInformation, pointer, (uint)length))
            {
                throw new InvalidOperationException("SetInformationJobObject failed.");
            }
        }
        finally
        {
            Marshal.FreeHGlobal(pointer);
        }

        return handle;
    }

    public static void Assign(IntPtr job, IntPtr process)
    {
        if (!AssignProcessToJobObject(job, process))
        {
            throw new InvalidOperationException("AssignProcessToJobObject failed.");
        }
    }
}
"@

$script:ProcessJob = [RoughCutJobObject]::CreateKillOnCloseJob()

function Initialize-RoughCutEnvironment {
    if (Test-Path $Python) {
        return
    }

    Write-Host "Python virtual environment not found. Bootstrapping RoughCut..." -ForegroundColor Yellow

    if ($null -ne $Uv) {
        Write-Host "Using uv to create and sync .venv" -ForegroundColor Cyan
        Invoke-NativeCommandChecked -FilePath $Uv.Source -Arguments @("sync", "--extra", "dev", "--extra", "local-asr") -FailureMessage "uv sync failed"
    } elseif ($null -ne $SystemPython) {
        Write-Host "uv not found. Falling back to python -m venv + pip install." -ForegroundColor Yellow
        Invoke-NativeCommandChecked -FilePath $SystemPython.Source -Arguments @("-m", "venv", ".venv") -FailureMessage "python -m venv failed"
        if (-not (Test-Path $Python)) {
            throw "Failed to create virtual environment: $Python"
        }
        Invoke-NativeCommandChecked -FilePath $Python -Arguments @("-m", "pip", "install", "-e", ".[dev,local-asr]") -FailureMessage "Backend dependency installation failed"
    } else {
        throw "Neither uv nor python is available. Install uv, then run 'uv sync --extra dev --extra local-asr'."
    }

    if (-not (Test-Path $Python)) {
        throw "Virtual environment Python not found after bootstrap: $Python"
    }
}

function Ensure-RoughCutFrontend {
    if (-not (Test-Path $FrontendDir)) {
        return
    }

    if ($null -eq $Pnpm) {
        throw "pnpm is required to build the React frontend. Enable Corepack or install pnpm, then rerun."
    }

    $needsBuild = -not (Test-Path $FrontendDist)
    if (-not $needsBuild) {
        $distTime = (Get-Item $FrontendDist).LastWriteTimeUtc
        $frontendInputs = @(
            (Join-Path $FrontendDir "package.json")
            (Join-Path $FrontendDir "vite.config.ts")
            (Join-Path $FrontendDir "tsconfig.app.json")
            (Join-Path $FrontendDir "tsconfig.node.json")
            (Join-Path $FrontendDir "tsconfig.json")
        ) | Where-Object { Test-Path $_ }

        $inputItems = @()
        $inputItems += $frontendInputs | ForEach-Object { Get-Item $_ }
        $inputItems += Get-ChildItem -Path $FrontendSrcDir -File -Recurse -ErrorAction SilentlyContinue
        $latestInput = $inputItems | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1

        if ($latestInput -and $latestInput.LastWriteTimeUtc -gt $distTime) {
            $needsBuild = $true
        }
    }

    if (-not $needsBuild) {
        return
    }

    Write-Host "Frontend build missing or stale. Installing and building React app with pnpm..." -ForegroundColor Yellow
    Push-Location $RepoRoot
    try {
        if (-not (Test-Path (Join-Path $RepoRoot "node_modules"))) {
            Invoke-NativeCommandChecked -FilePath $Pnpm.Source -Arguments @("install") -FailureMessage "pnpm install failed"
        }
        Invoke-NativeCommandChecked -FilePath $Pnpm.Source -Arguments @("build") -FailureMessage "Frontend build failed"
    } finally {
        Pop-Location
    }

    if (-not (Test-Path $FrontendDist)) {
        throw "Frontend build failed: $FrontendDist not found."
    }
}

function Test-PortListening {
    param([int]$TestPort)
    try {
        $conn = Get-NetTCPConnection -State Listen -LocalPort $TestPort -ErrorAction Stop | Select-Object -First 1
        return $null -ne $conn
    } catch {
        return $false
    }
}

function Is-TcpPortAvailable {
    param([int]$TestPort)
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $TestPort)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

function Get-LocalDotEnvValue {
    param([string]$Key)

    $dotEnvPath = Join-Path $RepoRoot ".env"
    if (-not (Test-Path $dotEnvPath)) {
        return $null
    }

    $escapedKey = [regex]::Escape($Key)
    foreach ($line in Get-Content $dotEnvPath) {
        if ($line -match "^\s*$escapedKey\s*=\s*([^#]*?)(\s+#.*)?$") {
            $raw = $Matches[1].Trim()
            if (($raw.StartsWith('"') -and $raw.EndsWith('"')) -or ($raw.StartsWith("'") -and $raw.EndsWith("'"))) {
                return $raw.Substring(1, $raw.Length - 2)
            }
            return $raw
        }
    }
    return $null
}

function Resolve-StandalonePort {
    param(
        [string]$EnvVarName,
        [int[]]$PreferredPorts,
        [hashtable]$UsedPorts
    )

    $candidateSources = @()
    $envEntry = Get-Item "env:$EnvVarName" -ErrorAction SilentlyContinue
    if ($envEntry) {
        $candidateSources += $envEntry.Value
    }

    $dotEnvValue = Get-LocalDotEnvValue -Key $EnvVarName
    if ($dotEnvValue) {
        $candidateSources += $dotEnvValue
    }

    foreach ($candidateSource in $candidateSources) {
        $candidate = Parse-PortValue -Value $candidateSource
        if ($null -eq $candidate) {
            continue
        }
        $candidateIsFree = Is-TcpPortAvailable -TestPort $candidate
        if (-not $UsedPorts.ContainsKey($candidate) -and $candidateIsFree) {
            $UsedPorts[$candidate] = $true
            return $candidate
        }
    }

    foreach ($candidate in $PreferredPorts) {
        $candidateIsFree = Is-TcpPortAvailable -TestPort $candidate
        if (-not $UsedPorts.ContainsKey($candidate) -and $candidateIsFree) {
            $UsedPorts[$candidate] = $true
            return $candidate
        }
    }

    for ($i = 0; $i -lt 4000; $i++) {
        $candidate = Get-Random -Minimum 42000 -Maximum 49150
        if ($UsedPorts.ContainsKey($candidate)) {
            continue
        }
        if (Is-TcpPortAvailable -TestPort $candidate) {
            $UsedPorts[$candidate] = $true
            return $candidate
        }
    }

    throw "Failed to allocate a free host port for $EnvVarName."
}

function Resolve-ContainerMappedPort {
    param(
        [string]$ContainerName,
        [int]$ContainerPort
    )

    try {
        $mapping = docker port $ContainerName "$ContainerPort/tcp" 2>$null | Select-Object -First 1
        if (-not $mapping) {
            return $null
        }
        if ($mapping -match ":(\d+)$") {
            return [int]$Matches[1]
        }
    } catch {
    }
    return $null
}

function Resolve-ServicePort {
    param(
        [string]$ContainerName,
        [int]$ContainerPort,
        [string]$EnvVarName,
        [int[]]$PreferredPorts,
        [hashtable]$UsedPorts
    )

    $mapped = Resolve-ContainerMappedPort -ContainerName $ContainerName -ContainerPort $ContainerPort
    if ($null -ne $mapped) {
        $UsedPorts[$mapped] = $true
        return $mapped
    }

    return Resolve-StandalonePort -EnvVarName $EnvVarName -PreferredPorts $PreferredPorts -UsedPorts $UsedPorts
}

function Test-IndexTTS2ServiceHealthy {
    param(
        [int]$Port,
        [int]$TimeoutSec = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
            if ($response.status -eq "ok" -and $response.service -eq "indextts2-service") {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)

    return $false
}

function Parse-PortValue {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    $candidate = 0
    if (-not [int]::TryParse($Value.Trim(), [ref]$candidate)) {
        return $null
    }
    if ($candidate -lt 1 -or $candidate -gt 65535) {
        return $null
    }
    return $candidate
}

function Resolve-PortSet {
    param(
        [hashtable]$UsedPorts
    )

    $postgresPort = Resolve-ServicePort -ContainerName "roughcut-postgres-1" -ContainerPort 5432 -EnvVarName "ROUGHCUT_POSTGRES_PORT" -PreferredPorts @(25432,25434,25436,25438,25440,25442,25444,25446) -UsedPorts $UsedPorts
    $redisPort = Resolve-ServicePort -ContainerName "roughcut-redis-1" -ContainerPort 6379 -EnvVarName "ROUGHCUT_REDIS_PORT" -PreferredPorts @(26379,26380,26381,26382,26383,26384,26385) -UsedPorts $UsedPorts
    $minioApiPort = Resolve-ServicePort -ContainerName "roughcut-minio-1" -ContainerPort 9000 -EnvVarName "MINIO_API_PORT" -PreferredPorts @(39000,39002,39004,39006,39008,39010,39012) -UsedPorts $UsedPorts
    $minioApiPortRaw = if ($minioApiPort -is [array]) { $minioApiPort[0] } else { $minioApiPort }
    $minioApiPortInt = 0
    if (-not [int]::TryParse("$minioApiPortRaw", [ref]$minioApiPortInt)) {
        throw "Failed to parse MINIO_API_PORT value: $minioApiPortRaw"
    }
    $minioApiPort = $minioApiPortInt
    $minioConsoleCandidates = @(
        ($minioApiPort + 1),
        39001, 39003, 39005, 39007, 39009, 39011
    )
    $minioConsolePort = Resolve-ServicePort -ContainerName "roughcut-minio-1" -ContainerPort 9001 -EnvVarName "MINIO_CONSOLE_PORT" -PreferredPorts $minioConsoleCandidates -UsedPorts $UsedPorts

    if ($minioConsolePort -eq $minioApiPort) {
        $UsedPorts.Remove($minioConsolePort)
        $minioConsolePort = Resolve-StandalonePort -EnvVarName "MINIO_CONSOLE_PORT" -PreferredPorts @(39001,39003,39005,39007,39009,39011) -UsedPorts $UsedPorts
    }

    $configuredHeygemApiPort = Parse-PortValue -Value $(if ($env:HEYGEM_API_PORT) { $env:HEYGEM_API_PORT } else { Get-LocalDotEnvValue -Key "HEYGEM_API_PORT" })
    $configuredIndexTtsPort = Parse-PortValue -Value $(if ($env:INDEXTTS2_API_PORT) { $env:INDEXTTS2_API_PORT } else { Get-LocalDotEnvValue -Key "INDEXTTS2_API_PORT" })
    if ($null -eq $configuredIndexTtsPort) {
        $configuredIndexTtsPort = Parse-PortValue -Value $(if ($env:HEYGEM_TRAINING_API_PORT) { $env:HEYGEM_TRAINING_API_PORT } else { Get-LocalDotEnvValue -Key "HEYGEM_TRAINING_API_PORT" })
    }
    $heygemApiPort = if ($null -ne $configuredHeygemApiPort) { $configuredHeygemApiPort } else { 49202 }
    $heygemTrainingPort = if ($null -ne $configuredIndexTtsPort) { $configuredIndexTtsPort } else { 49204 }

    return @{
        Postgres = $postgresPort
        Redis = $redisPort
        MinioApi = $minioApiPort
        MinioConsole = $minioConsolePort
        HeygemApi = $heygemApiPort
        HeygemTraining = $heygemTrainingPort
    }
}

function Resolve-ApiPort {
    param(
        [hashtable]$UsedPorts,
        [int]$RequestedPort = 0
    )

    if ($RequestedPort -gt 0) {
        $candidate = Parse-PortValue -Value "$RequestedPort"
        $candidateIsFree = $false
        if ($null -ne $candidate) {
            $candidateIsFree = Is-TcpPortAvailable -TestPort $candidate
        }
        if ($null -ne $candidate -and -not $UsedPorts.ContainsKey($candidate) -and $candidateIsFree) {
            $UsedPorts[$candidate] = $true
            return $candidate
        }
    }

    $envCandidates = @()
    if ($env:ROUGHCUT_API_PORT) {
        $envCandidates += $env:ROUGHCUT_API_PORT
    }
    $dotEnvValue = Get-LocalDotEnvValue -Key "ROUGHCUT_API_PORT"
    if ($dotEnvValue) {
        $envCandidates += $dotEnvValue
    }

    foreach ($candidateSource in $envCandidates) {
        $candidate = Parse-PortValue -Value $candidateSource
        if ($null -eq $candidate) {
            continue
        }
        $candidateIsFree = Is-TcpPortAvailable -TestPort $candidate
        if (-not $UsedPorts.ContainsKey($candidate) -and $candidateIsFree) {
            $UsedPorts[$candidate] = $true
            return $candidate
        }
    }

    return Resolve-StandalonePort -EnvVarName "ROUGHCUT_API_PORT" -PreferredPorts @(38471, 38472, 38473, 38474, 38475, 38476, 38477) -UsedPorts $UsedPorts
}

function Update-LocalServiceEnv {
    param(
        [int]$PostgresPort,
        [int]$RedisPort,
        [int]$MinioApiPort,
        [int]$MinioConsolePort,
        [int]$HeygemApiPort,
        [int]$HeygemTrainingPort,
        [int]$ApiPort
    )

    $defaultHeygemRoot = "E:/WorkSpace/heygem/data"
    $heygemSharedRoot = if ($env:HEYGEM_SHARED_ROOT -and -not [string]::IsNullOrWhiteSpace($env:HEYGEM_SHARED_ROOT)) {
        [System.IO.Path]::GetFullPath($env:HEYGEM_SHARED_ROOT).Replace('\\', '/')
    } else {
        $defaultHeygemRoot
    }
    if (-not (Test-Path $heygemSharedRoot)) {
        New-Item -ItemType Directory -Force -Path $heygemSharedRoot | Out-Null
    }

    $env:ROUGHCUT_POSTGRES_PORT = "$PostgresPort"
    $env:ROUGHCUT_REDIS_PORT = "$RedisPort"
    $env:MINIO_API_PORT = "$MinioApiPort"
    $env:MINIO_CONSOLE_PORT = "$MinioConsolePort"
    $env:HEYGEM_API_PORT = "$HeygemApiPort"
    $env:INDEXTTS2_API_PORT = "$HeygemTrainingPort"
    $env:HEYGEM_SHARED_HOST_DIR = $heygemSharedRoot
    $env:HEYGEM_SHARED_ROOT = $heygemSharedRoot
    $voiceRoot = if ($env:HEYGEM_VOICE_ROOT -and -not [string]::IsNullOrWhiteSpace($env:HEYGEM_VOICE_ROOT)) {
        [System.IO.Path]::GetFullPath($env:HEYGEM_VOICE_ROOT).Replace('\\', '/')
    } else {
        "E:/WorkSpace/RoughCut/data/voice_refs"
    }
    if (-not (Test-Path $voiceRoot)) {
        New-Item -ItemType Directory -Force -Path $voiceRoot | Out-Null
    }
    $env:HEYGEM_VOICE_ROOT = $voiceRoot
    $env:AVATAR_API_BASE_URL = "http://127.0.0.1:$HeygemApiPort"
    $env:AVATAR_TRAINING_API_BASE_URL = "http://127.0.0.1:$HeygemTrainingPort"

    $dbEnv = Get-LocalDotEnvValue -Key "DATABASE_URL"
    if ($dbEnv -match "^(?<prefix>postgresql\+asyncpg://[^@]+@[^:]+:)(?<port>\d+)(?<suffix>/[A-Za-z0-9_-]+)$") {
        $env:DATABASE_URL = "$($Matches['prefix'])$PostgresPort$($Matches['suffix'])"
    } else {
        $env:DATABASE_URL = "postgresql+asyncpg://roughcut:roughcut@localhost:$PostgresPort/roughcut"
    }

    $redisEnv = Get-LocalDotEnvValue -Key "REDIS_URL"
    if ($redisEnv -match "^(?<prefix>redis://[^:]+:)(?<port>\d+)(?<suffix>/\d+)$") {
        $env:REDIS_URL = "$($Matches['prefix'])$RedisPort$($Matches['suffix'])"
    } else {
        $env:REDIS_URL = "redis://localhost:$RedisPort/0"
    }
    $env:CELERY_BROKER_URL = "redis://localhost:$RedisPort/0"
    $env:CELERY_RESULT_BACKEND = "redis://localhost:$RedisPort/1"

    $s3Endpoint = Get-LocalDotEnvValue -Key "S3_ENDPOINT_URL"
    $shouldRewriteS3Endpoint = $true
    if (-not [string]::IsNullOrWhiteSpace($s3Endpoint)) {
        try {
            $s3Uri = [uri]$s3Endpoint
            if ($s3Uri.Host -and $s3Uri.Host -notin @("localhost", "127.0.0.1")) {
                $shouldRewriteS3Endpoint = $false
            }
        } catch {
            $shouldRewriteS3Endpoint = $true
        }
    }
    if ($shouldRewriteS3Endpoint) {
        $env:S3_ENDPOINT_URL = "http://127.0.0.1:$MinioApiPort"
    }
    $env:ROUGHCUT_API_PORT = "$ApiPort"
    Write-Host "Allocated ports -> PostgreSQL:$PostgresPort Redis:$RedisPort MinIO API:$MinioApiPort MinIO Console:$MinioConsolePort External HeyGem:$HeygemApiPort/$HeygemTrainingPort API:$ApiPort" -ForegroundColor Cyan
}

function Get-ProcessMatches {
    param([string]$Pattern)

    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "python.exe" `
            -and $_.ExecutablePath `
            -and (Test-Path $Python) `
            -and [System.StringComparer]::OrdinalIgnoreCase.Equals($_.ExecutablePath, $Python) `
            -and $_.CommandLine `
            -and $_.CommandLine -match $Pattern
    } | Sort-Object ProcessId)
}

function Stop-RoughCutProcess {
    param(
        [string]$Name,
        [string]$Pattern
    )

    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match $Pattern
    })

    if ($processes.Count -eq 0) {
        Write-Host "$Name is not running." -ForegroundColor Yellow
        return
    }

    foreach ($proc in $processes) {
        try {
            $alive = Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue
            if (-not $alive) {
                Write-Host "$Name already exited (PID $($proc.ProcessId))." -ForegroundColor Yellow
                continue
            }

            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Host "$Name stopped (PID $($proc.ProcessId))." -ForegroundColor Green
        } catch {
            $message = $_.Exception.Message
            if ($message -match "Cannot find a process with the process identifier") {
                Write-Host "$Name already exited (PID $($proc.ProcessId))." -ForegroundColor Yellow
            } else {
                Write-Host "Failed to stop $Name (PID $($proc.ProcessId)): $message" -ForegroundColor Red
            }
        }
    }
}

function Stop-RoughCutServices {
    param([switch]$StopDockerServices)

    Write-Host "Stopping existing RoughCut services..." -ForegroundColor Cyan
    Stop-RoughCutProcess -Name "API" -Pattern "roughcut\.cli api --host 127\.0\.0\.1 --port"
    Stop-RoughCutProcess -Name "Orchestrator" -Pattern "roughcut\.cli orchestrator --poll-interval"
    Stop-RoughCutProcess -Name "Media worker" -Pattern "celery -A roughcut\.pipeline\.celery_app:celery_app worker --queues=media_queue"
    Stop-RoughCutProcess -Name "LLM worker" -Pattern "celery -A roughcut\.pipeline\.celery_app:celery_app worker --queues=llm_queue"
    Stop-RoughCutProcess -Name "Watcher" -Pattern "roughcut\.cli watcher"

    if ($StopDockerServices) {
        Write-Host "Stopping docker compose services..." -ForegroundColor Cyan
        docker compose stop | Out-Host
    }
}

function Remove-LegacyHeygemMockContainer {
    $legacyContainer = "roughcut-heygem-1"
    $exists = docker ps -a --filter "name=^${legacyContainer}$" --format "{{.Names}}"
    if (-not [string]::IsNullOrWhiteSpace($exists)) {
        Write-Host "Removing legacy mock container $legacyContainer..." -ForegroundColor Yellow
        docker rm -f $legacyContainer | Out-Host
    }
}

function Start-RoughCutProcess {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [string]$MatchPattern,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    $matches = @(Get-ProcessMatches -Pattern $MatchPattern)
    if ($matches.Count -gt 1) {
        $matches | Select-Object -SkipLast 1 | ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
                Write-Host "Stopped duplicate $Name (PID $($_.ProcessId))." -ForegroundColor Yellow
            } catch {
            }
        }
        $matches = @(Get-ProcessMatches -Pattern $MatchPattern)
    }

    if ($matches.Count -eq 1) {
        Write-Host "$Name is already running. Skipping." -ForegroundColor Yellow
        return
    }

    $process = Start-Process `
        -FilePath $Python `
        -ArgumentList $Arguments `
        -WorkingDirectory $RepoRoot `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath

    [RoughCutJobObject]::Assign($script:ProcessJob, $process.Handle)
    $script:ManagedProcesses += [pscustomobject]@{
        Name = $Name
        Process = $process
    }

    Write-Host "$Name started (PID $($process.Id))." -ForegroundColor Green
}

function Wait-ApiReady {
    param(
        [int]$TestPort,
        [int]$TimeoutSec = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $url = "http://127.0.0.1:$TestPort/health"
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -ne 200) {
                Start-Sleep -Milliseconds 500
                continue
            }
            if ($response.Content -match '"status"\s*:\s*"ok"') {
                return $true
            }
        } catch {
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Wait-LocalPortListening {
    param(
        [int]$TestPort,
        [string]$ServiceName,
        [int]$TimeoutSec = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening -TestPort $TestPort) {
            Write-Host "$ServiceName is listening on port $TestPort." -ForegroundColor Green
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    Write-Host "$ServiceName did not start on port $TestPort within $TimeoutSec seconds." -ForegroundColor Red
    return $false
}

function Wait-LauncherClose {
    if ($StopOnly) {
        return
    }

    Write-Host ""
    if ($NoPause) {
        Write-Host "-NoPause is ignored because this launcher window now owns the RoughCut processes." -ForegroundColor Yellow
    }
    Write-Host "This launcher window owns the running RoughCut services." -ForegroundColor DarkGray
    Write-Host "Close this terminal window to stop API / orchestrator / workers together." -ForegroundColor DarkGray
    Write-Host "Logs stay in .\logs\*.out.log / .\logs\*.err.log" -ForegroundColor DarkGray

    $notified = @{}
    while ($true) {
        foreach ($entry in $script:ManagedProcesses) {
            if ($entry.Process.HasExited -and -not $notified.ContainsKey($entry.Process.Id)) {
                $notified[$entry.Process.Id] = $true
                Write-Host "$($entry.Name) exited with code $($entry.Process.ExitCode)." -ForegroundColor Yellow
            }
        }
        Start-Sleep -Seconds 2
    }
}

if ($StopOnly) {
Stop-RoughCutServices -StopDockerServices:$StopDocker
Stop-RoughCutDockerWatch -ComposeMode all -SilentlyContinue
Remove-LegacyHeygemMockContainer
    exit 0
}

if ($Mode -in @("runtime-watch", "full-watch")) {
    Start-RoughCutDockerWatchMode -WatchMode $Mode
    exit 0
}

if ($Mode -eq "runtime-down") {
    Stop-RoughCutComposeMode -ComposeMode "runtime"
    exit 0
}

if ($Mode -eq "full-down") {
    Stop-RoughCutComposeMode -ComposeMode "full"
    exit 0
}

if ($Mode -ne "local") {
    Start-RoughCutComposeMode -ComposeMode $Mode
    if ($Mode -in @("runtime", "full")) {
        Start-RoughCutDockerWatch -ComposeMode $Mode
    }
    exit 0
}

Initialize-RoughCutEnvironment
Ensure-RoughCutFrontend

Stop-RoughCutServices

    if (-not $SkipDocker) {
        Write-Host "Checking Docker services..." -ForegroundColor Cyan
    $dockerContainers = @("roughcut-postgres-1", "roughcut-redis-1", "roughcut-minio-1")
    $dockerServices = @("postgres", "redis", "minio")
        $legacyDockerNames = @("fastcut-postgres-1", "fastcut-redis-1", "fastcut-minio-1")
    $usedPorts = @{}
    try {
        $running = docker ps -a --format "{{.Names}}"
    } catch {
        throw "Failed to run docker. Make sure Docker Desktop is running."
    }

    $legacy = @($legacyDockerNames | Where-Object { $_ -in $running })
    if ($legacy.Count -gt 0) {
        if (-not $CleanupLegacyDocker) {
            throw "Legacy FastCut containers detected: $($legacy -join ', '). Run 'docker rm -f $($legacy -join ' ')' or rerun with -CleanupLegacyDocker."
        }
        Write-Host "Removing legacy FastCut containers..." -ForegroundColor Yellow
        docker rm -f $legacy | Out-Host
    }

    $servicePorts = Resolve-PortSet -UsedPorts $usedPorts
    $requestedApiPort = if ($PSBoundParameters.ContainsKey("Port")) { $Port } else { 0 }
    $resolvedApiPort = Resolve-ApiPort -UsedPorts $usedPorts -RequestedPort $requestedApiPort

    Update-LocalServiceEnv -PostgresPort $servicePorts.Postgres -RedisPort $servicePorts.Redis -MinioApiPort $servicePorts.MinioApi -MinioConsolePort $servicePorts.MinioConsole -HeygemApiPort $servicePorts.HeygemApi -HeygemTrainingPort $servicePorts.HeygemTraining -ApiPort $resolvedApiPort
    $Port = $resolvedApiPort

    Write-Host "Starting docker compose services..." -ForegroundColor Yellow
    docker compose up -d $dockerServices | Out-Host

    if (-not (Wait-LocalPortListening -TestPort $servicePorts.Postgres -ServiceName "PostgreSQL" -TimeoutSec 60)) {
        throw "PostgreSQL failed to start in time."
    }
    if (-not (Wait-LocalPortListening -TestPort $servicePorts.Redis -ServiceName "Redis" -TimeoutSec 60)) {
        throw "Redis failed to start in time."
    }
    if (-not (Wait-LocalPortListening -TestPort $servicePorts.MinioApi -ServiceName "MinIO API" -TimeoutSec 90)) {
        throw "MinIO failed to start in time."
    }
    if (-not (Wait-LocalPortListening -TestPort $servicePorts.MinioConsole -ServiceName "MinIO Console" -TimeoutSec 90)) {
        throw "MinIO Console failed to start in time."
    }
    if (Wait-LocalPortListening -TestPort $servicePorts.HeygemApi -ServiceName "HeyGem API (external)" -TimeoutSec 2) {
        Write-Host "External HeyGem preview service is already running." -ForegroundColor Green
    } else {
        Write-Host "External HeyGem preview service is currently stopped; RoughCut will start the managed Docker stack on first demand." -ForegroundColor Yellow
    }
    if (Wait-LocalPortListening -TestPort $servicePorts.HeygemTraining -ServiceName "IndexTTS2 / Voice Synthesis" -TimeoutSec 2) {
        if (-not (Test-IndexTTS2ServiceHealthy -Port $servicePorts.HeygemTraining -TimeoutSec 20)) {
            Write-Host "External IndexTTS2 port is open but health payload is not ready yet; RoughCut will retry on first demand." -ForegroundColor Yellow
        }
    } else {
        Write-Host "IndexTTS2 service is currently stopped; RoughCut will start the managed Docker stack on first demand." -ForegroundColor Yellow
    }

    Write-Host "Docker services are ready." -ForegroundColor Green
}

if (-not $SkipMigrate) {
    Write-Host "Running database migrations..." -ForegroundColor Cyan
    Invoke-NativeCommandChecked -FilePath $Python -Arguments @("-m", "roughcut.cli", "migrate") -FailureMessage "Database migrations failed"
}

New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "logs") | Out-Null
New-Item -ItemType Directory -Force -Path $WatchDir | Out-Null

Write-Host "Starting RoughCut services..." -ForegroundColor Cyan
if (-not $NoWatcher) {
    Start-RoughCutProcess `
        -Name "Watcher" `
        -Arguments @("-m", "roughcut.cli", "watcher", $WatchDir, "--language", "zh-CN") `
        -MatchPattern ([regex]::Escape("roughcut.cli watcher $WatchDir --language zh-CN")) `
        -StdoutPath (Join-Path $RepoRoot "logs\watcher.out.log") `
        -StderrPath (Join-Path $RepoRoot "logs\watcher.err.log")
}
Start-RoughCutProcess `
    -Name "API" `
    -Arguments @("-m", "roughcut.cli", "api", "--host", "127.0.0.1", "--port", "$Port") `
    -MatchPattern ([regex]::Escape("roughcut.cli api --host 127.0.0.1 --port $Port")) `
    -StdoutPath (Join-Path $RepoRoot "logs\api.out.log") `
    -StderrPath (Join-Path $RepoRoot "logs\api.err.log")
Start-RoughCutProcess `
    -Name "Orchestrator" `
    -Arguments @("-m", "roughcut.cli", "orchestrator", "--poll-interval", "2") `
    -MatchPattern ([regex]::Escape("roughcut.cli orchestrator --poll-interval 2")) `
    -StdoutPath (Join-Path $RepoRoot "logs\orchestrator.out.log") `
    -StderrPath (Join-Path $RepoRoot "logs\orchestrator.err.log")
Start-RoughCutProcess `
    -Name "Media worker" `
    -Arguments @("-m", "celery", "-A", "roughcut.pipeline.celery_app:celery_app", "worker", "--queues=media_queue", "--pool=solo", "--concurrency=1", "--loglevel=info") `
    -MatchPattern ([regex]::Escape("celery -A roughcut.pipeline.celery_app:celery_app worker --queues=media_queue --pool=solo --concurrency=1 --loglevel=info")) `
    -StdoutPath (Join-Path $RepoRoot "logs\media-worker.out.log") `
    -StderrPath (Join-Path $RepoRoot "logs\media-worker.err.log")
Start-RoughCutProcess `
    -Name "LLM worker" `
    -Arguments @("-m", "celery", "-A", "roughcut.pipeline.celery_app:celery_app", "worker", "--queues=llm_queue", "--pool=solo", "--concurrency=1", "--loglevel=info") `
    -MatchPattern ([regex]::Escape("celery -A roughcut.pipeline.celery_app:celery_app worker --queues=llm_queue --pool=solo --concurrency=1 --loglevel=info")) `
    -StdoutPath (Join-Path $RepoRoot "logs\llm-worker.out.log") `
    -StderrPath (Join-Path $RepoRoot "logs\llm-worker.err.log")

Write-Host ""
Write-Host "RoughCut started." -ForegroundColor Green
Write-Host "API URL: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Logs: .\logs\*.out.log / .\logs\*.err.log" -ForegroundColor DarkGray

if (Wait-ApiReady -TestPort $Port) {
    Start-Process "http://127.0.0.1:$Port/" | Out-Null
    Write-Host "GUI opened in your default browser." -ForegroundColor Green
} else {
    Write-Host "API did not become ready in time. Check logs if the GUI does not open." -ForegroundColor Yellow
}

Wait-LauncherClose
