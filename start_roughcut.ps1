param(
    [ValidateSet("local", "infra", "runtime", "full", "runtime-watch", "full-watch", "runtime-down", "full-down", "install-autostart", "uninstall-autostart")]
    [string]$Mode = "full",
    [string]$DockerPythonExtras = "",
    [int]$Port = 0,
    [ValidateRange(1, 8)]
    [int]$MediaWorkerCount = 1,
    [ValidateRange(1, 16)]
    [int]$LlmWorkerCount = 4,
    [switch]$SkipDocker,
    [switch]$SkipMigrate,
    [switch]$CleanupLegacyDocker,
    [switch]$StopOnly,
    [switch]$StopDocker,
    [switch]$NoPause,
    [switch]$SafeStart,
    [switch]$OpenBrowser,
    [switch]$FrontendDev,
    [switch]$NoFrontendDev,
    [switch]$NoOrchestrator,
    [switch]$NoWorkers,
    [switch]$NoAutoResume,
    [switch]$NoWatchAutoDuty,
    [switch]$NoWatcher,
    [switch]$NoDockerWatch,
    [switch]$AutoDockerWatch,
    [switch]$BuildDocker
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
$FrontendDevDefaultPort = 5173
$WatchDir = Join-Path $RepoRoot "watch"
$InfraComposeFile = Join-Path $RepoRoot "docker-compose.infra.yml"
$RuntimeComposeFile = Join-Path $RepoRoot "docker-compose.runtime.yml"
$DevComposeFile = Join-Path $RepoRoot "docker-compose.dev.yml"
$AutomationComposeFile = Join-Path $RepoRoot "docker-compose.automation.yml"
$PortsEnvFile = Join-Path $RepoRoot "roughcut.ports.env"
$DockerWatchScript = Join-Path $RepoRoot "scripts\watch-roughcut-docker-runtime.ps1"
$EnsureTelegramAgentScript = Join-Path $RepoRoot "scripts\ensure-roughcut-telegram-agent.ps1"
$StopTelegramAgentScript = Join-Path $RepoRoot "scripts\stop-roughcut-telegram-agent.ps1"
$CodexHostBridgeScript = Join-Path $RepoRoot "scripts\codex_host_bridge.py"
$CodexHostBridgeEnvFile = Join-Path $RepoRoot "logs\codex-host-bridge.env"
$CodexHostBridgeOutLog = Join-Path $RepoRoot "logs\codex-host-bridge.out.log"
$CodexHostBridgeErrLog = Join-Path $RepoRoot "logs\codex-host-bridge.err.log"
$CodexHostBridgePort = 38695
$CodexHostBridgeBindHost = "0.0.0.0"
$ApiBindHost = "0.0.0.0"
$DockerAutostartTaskName = "RoughCut Docker Dev"
$DockerAutostartShortcutName = "RoughCut Docker Dev.lnk"
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

function Invoke-NativeCommandUnchecked {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $previousNativeCommandUseErrorActionPreference = $null
    try {
        $ErrorActionPreference = "Continue"
        if ($PSVersionTable.PSVersion.Major -ge 7) {
            $previousNativeCommandUseErrorActionPreference = $PSNativeCommandUseErrorActionPreference
            $PSNativeCommandUseErrorActionPreference = $false
        }

        & $FilePath @Arguments
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($PSVersionTable.PSVersion.Major -ge 7) {
            $PSNativeCommandUseErrorActionPreference = $previousNativeCommandUseErrorActionPreference
        }
    }
}

function Wait-RoughCutDockerDaemon {
    param([int]$TimeoutSec = 180)

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $docker) {
        throw "Docker Desktop is required for Docker modes."
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $lastError = ""
    $startedDockerDesktop = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $output = & $docker.Source info --format "{{.ServerVersion}}" 2>&1
            if ($LASTEXITCODE -eq 0) {
                return $docker
            }
            $lastError = ($output | Out-String).Trim()
        } catch {
            $lastError = $_.Exception.Message
        }

        if (-not $startedDockerDesktop) {
            $dockerDesktopPath = if ([string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
                ""
            } else {
                Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
            }
            if (-not [string]::IsNullOrWhiteSpace($dockerDesktopPath) -and (Test-Path $dockerDesktopPath)) {
                $runningDockerDesktop = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
                if ($null -eq $runningDockerDesktop) {
                    Write-Host "Starting Docker Desktop..." -ForegroundColor DarkGray
                    Start-Process -FilePath $dockerDesktopPath -WindowStyle Hidden | Out-Null
                }
            }
            $startedDockerDesktop = $true
        }

        Write-Host "Waiting for Docker Desktop to become ready..." -ForegroundColor DarkGray
        Start-Sleep -Seconds 3
    }

    $detail = if ([string]::IsNullOrWhiteSpace($lastError)) { "Docker daemon did not respond." } else { $lastError }
    throw "Docker Desktop did not become ready within $TimeoutSec seconds. $detail"
}

function Get-RoughCutComposeFiles {
    param(
        [ValidateSet("infra", "runtime", "full")]
        [string]$ComposeMode
    )

    $files = @($InfraComposeFile)
    if ($ComposeMode -in @("runtime", "full")) {
        $files += $RuntimeComposeFile
        $files += $DevComposeFile
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

    $docker = Wait-RoughCutDockerDaemon

    $composeFiles = Get-RoughCutComposeFiles -ComposeMode $ComposeMode
    $args = @("compose")
    if (Test-Path $PortsEnvFile) {
        $args += "--env-file"
        $args += $PortsEnvFile
    }
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

function Remove-RoughCutStoppedComposeContainers {
    param(
        [string[]]$ServiceNames = @(
            "postgres",
            "redis",
            "minio",
            "api",
            "orchestrator",
            "worker-media",
            "worker-llm",
            "worker-agent",
            "worker-publication",
            "watcher",
            "migrate"
        )
    )

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $docker) {
        return
    }

    $composeEntries = docker ps -a --format "{{.Names}}|{{.State}}"
    if (-not $composeEntries) {
        return
    }

    $escapedServices = $ServiceNames | ForEach-Object { [regex]::Escape($_) }
    $serviceRegex = "^(?:[^_]+_)?roughcut-(?:$($escapedServices -join "|"))-\d+$"
    $staleContainers = @()

    foreach ($entry in ($composeEntries -split "(`r`n|`n|`r)")) {
        $trimmed = $entry.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }

        $parts = $trimmed -split "\|", 2
        if ($parts.Count -ne 2) {
            continue
        }

        $name = $parts[0]
        $state = $parts[1].ToLowerInvariant()
        if ($state -notin @("exited", "created", "dead")) {
            continue
        }

        if ($name -match $serviceRegex) {
            $staleContainers += $name
        }
    }

    if ($staleContainers.Count -eq 0) {
        return
    }

    $staleContainers = $staleContainers | Sort-Object -Unique
    Write-Host "Removing stale stopped RoughCut containers before compose startup: $($staleContainers -join ', ')" -ForegroundColor Yellow
    docker rm -f $staleContainers | Out-Null
}

function Get-RoughCutComposeStatusEntries {
    param(
        [ValidateSet("infra", "runtime", "full")]
        [string]$ComposeMode
    )

    $docker = Wait-RoughCutDockerDaemon

    $composeFiles = Get-RoughCutComposeFiles -ComposeMode $ComposeMode
    $args = @("compose")
    if (Test-Path $PortsEnvFile) {
        $args += "--env-file"
        $args += $PortsEnvFile
    }
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

    $requiredRunningServices = @("postgres", "redis", "minio", "api", "orchestrator", "worker-media", "worker-llm", "worker-agent", "worker-publication")
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
            Remove-RoughCutStoppedComposeContainers -ServiceNames @("postgres", "redis", "minio")
            Invoke-RoughCutCompose -ComposeMode $ComposeMode -ComposeArguments @("up", "-d")
        }
        default {
            $upArgs = @("up", "-d")
            $shouldBuild = $BuildDocker
            if ($shouldBuild) {
                $upArgs = @("up", "-d", "--build")
            }
            Remove-RoughCutStoppedComposeContainers
            Invoke-RoughCutCompose -ComposeMode $ComposeMode -ComposeArguments $upArgs -DockerPythonExtrasOverride $DockerPythonExtras
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
            Write-Host "Docker live source sync is active for this runtime." -ForegroundColor Green
            if (-not $BuildDocker) {
                Write-Host "Image rebuild skipped; source changes are hot-mounted. Use -BuildDocker after dependency or Dockerfile changes." -ForegroundColor DarkGray
            }
        }
        "full" {
            Write-Host "Runtime plus automation services are up." -ForegroundColor Green
            Write-Host "Docker live source sync is active for this runtime." -ForegroundColor Green
            if (-not $BuildDocker) {
                Write-Host "Image rebuild skipped; source changes are hot-mounted. Use -BuildDocker after dependency or Dockerfile changes." -ForegroundColor DarkGray
            }
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
    Invoke-RoughCutCompose -ComposeMode $ComposeMode -ComposeArguments @("down")
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

    $commandLine = if ($null -ne $process.CommandLine) { [string]$process.CommandLine } else { "" }
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

function Install-RoughCutDockerAutostart {
    $powerShellCommand = Get-PowerShellCommand
    $scriptPath = if ([string]::IsNullOrWhiteSpace($PSCommandPath)) {
        Join-Path $RepoRoot "start_roughcut.ps1"
    } else {
        $PSCommandPath
    }
    $taskAction = "`"$($powerShellCommand.Source)`" -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Mode full"

    Write-Host "Installing Windows logon task: $DockerAutostartTaskName" -ForegroundColor Cyan
    $taskExitCode = 0
    try {
        $taskOutput = & schtasks.exe /Create /TN $DockerAutostartTaskName /SC ONLOGON /RL LIMITED /F /TR $taskAction 2>&1
        $taskExitCode = $LASTEXITCODE
    } catch {
        $taskOutput = @($_.Exception.Message)
        $taskExitCode = 1
    }
    $taskOutput | Out-Host
    if ($taskExitCode -ne 0) {
        Write-Warning "Windows Task Scheduler refused the logon task; installing a current-user Startup shortcut instead."
        $startupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
        if ([string]::IsNullOrWhiteSpace($startupDir)) {
            throw "Failed to resolve current-user Startup folder after task registration failed."
        }
        $shortcutPath = Join-Path $startupDir $DockerAutostartShortcutName
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $powerShellCommand.Source
        $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Mode full"
        $shortcut.WorkingDirectory = $RepoRoot
        $shortcut.WindowStyle = 7
        $shortcut.Save()
        Write-Host "Installed current-user Startup shortcut: $shortcutPath" -ForegroundColor Green
    } else {
        Write-Host "Installed Windows logon task: $DockerAutostartTaskName" -ForegroundColor Green
    }

    Write-Host "RoughCut Docker full dev mode will start automatically at Windows logon." -ForegroundColor Green
    Write-Host "The task runs without --build; use './start_roughcut.bat rebuild' after dependency or Dockerfile changes." -ForegroundColor DarkGray
}

function Uninstall-RoughCutDockerAutostart {
    Write-Host "Removing Windows logon task: $DockerAutostartTaskName" -ForegroundColor Cyan
    $taskExitCode = 0
    try {
        $taskOutput = & schtasks.exe /Delete /TN $DockerAutostartTaskName /F 2>&1
        $taskExitCode = $LASTEXITCODE
    } catch {
        $taskOutput = @($_.Exception.Message)
        $taskExitCode = 1
    }
    $taskOutput | Out-Host
    if ($taskExitCode -ne 0) {
        Write-Warning "Windows logon task was not removed or did not exist."
    }

    $startupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
    if (-not [string]::IsNullOrWhiteSpace($startupDir)) {
        $shortcutPath = Join-Path $startupDir $DockerAutostartShortcutName
        if (Test-Path -LiteralPath $shortcutPath) {
            Remove-Item -LiteralPath $shortcutPath -Force
            Write-Host "Removed current-user Startup shortcut: $shortcutPath" -ForegroundColor Green
        }
    }

    Write-Host "RoughCut Docker autostart removed." -ForegroundColor Green
}

function Get-RoughCutCodexHostBridgeToken {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
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

    $commandLine = if ($null -ne $process.CommandLine) { [string]$process.CommandLine } else { "" }
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
        Invoke-NativeCommandChecked -FilePath $Uv.Source -Arguments @("sync", "--extra", "dev") -FailureMessage "uv sync failed"
    } elseif ($null -ne $SystemPython) {
        Write-Host "uv not found. Falling back to python -m venv + pip install." -ForegroundColor Yellow
        Invoke-NativeCommandChecked -FilePath $SystemPython.Source -Arguments @("-m", "venv", ".venv") -FailureMessage "python -m venv failed"
        if (-not (Test-Path $Python)) {
            throw "Failed to create virtual environment: $Python"
        }
        Invoke-NativeCommandChecked -FilePath $Python -Arguments @("-m", "pip", "install", "-e", ".[dev]") -FailureMessage "Backend dependency installation failed"
    } else {
        throw "Neither uv nor python is available. Install uv, then run 'uv sync --extra dev'."
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

    $escapedKey = [regex]::Escape($Key)
    $envFiles = @(
        (Join-Path $RepoRoot "roughcut.ports.env"),
        (Join-Path $RepoRoot ".env")
    )

    foreach ($dotEnvPath in $envFiles) {
        if (-not (Test-Path $dotEnvPath)) {
            continue
        }
        foreach ($line in Get-Content $dotEnvPath) {
            if ($line -match "^\s*$escapedKey\s*=\s*([^#]*?)(\s+#.*)?$") {
                $raw = $Matches[1].Trim()
                if (($raw.StartsWith('"') -and $raw.EndsWith('"')) -or ($raw.StartsWith("'") -and $raw.EndsWith("'"))) {
                    return $raw.Substring(1, $raw.Length - 2)
                }
                return $raw
            }
        }
    }
    return $null
}

function Get-ConfiguredValue {
    param([string]$Key)

    $envEntry = Get-Item "env:$Key" -ErrorAction SilentlyContinue
    if ($envEntry -and -not [string]::IsNullOrWhiteSpace($envEntry.Value)) {
        return $envEntry.Value.Trim()
    }

    $dotEnvValue = Get-LocalDotEnvValue -Key $Key
    if (-not [string]::IsNullOrWhiteSpace($dotEnvValue)) {
        return $dotEnvValue.Trim()
    }
    return ""
}

function Get-ConfiguredProviderValue {
    param([string]$Key)

    $value = Get-ConfiguredValue -Key $Key
    if ([string]::IsNullOrWhiteSpace($value)) {
        return ""
    }
    return $value.Trim().ToLowerInvariant()
}

function Get-ConfiguredValueOrDefault {
    param(
        [string]$Key,
        [string]$DefaultValue = ""
    )

    $value = Get-ConfiguredValue -Key $Key
    if (-not [string]::IsNullOrWhiteSpace($value)) {
        return $value
    }
    return $DefaultValue
}

function Get-ConfiguredVoiceProvider {
    return Get-ConfiguredProviderValue -Key "VOICE_PROVIDER"
}

function Get-ConfiguredAvatarProvider {
    $provider = Get-ConfiguredProviderValue -Key "AVATAR_PROVIDER"
    if ($provider) {
        return $provider
    }
    return "heygem"
}

function Get-ConfiguredTranscriptionProvider {
    $provider = Get-ConfiguredProviderValue -Key "TRANSCRIPTION_PROVIDER"
    switch ($provider) {
        "local-asr" { return "local_http_asr" }
        "local_asr" { return "local_http_asr" }
        "local-http-asr" { return "local_http_asr" }
        "" { return "faster_whisper" }
        default { return $provider }
    }
}

function Test-IndexTTS2StartupProbeEnabled {
    $voiceProvider = Get-ConfiguredVoiceProvider
    return $voiceProvider -eq "indextts2"
}

function Test-LocalHttpBaseUrl {
    param([string]$BaseUrl)

    if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
        return $false
    }
    try {
        $uri = [uri]$BaseUrl
        return $uri.Scheme -in @("http", "https") -and $uri.Host -in @("localhost", "127.0.0.1", "::1", "0.0.0.0")
    } catch {
        return $false
    }
}

function Get-BaseUrlPort {
    param([string]$BaseUrl)

    try {
        $uri = [uri]$BaseUrl
        if ($uri.Port -gt 0) {
            return $uri.Port
        }
    } catch {
    }
    return $null
}

function Get-BaseUrlWithPort {
    param(
        [string]$BaseUrl,
        [int]$Port
    )

    if ($Port -le 0) {
        return $BaseUrl
    }
    try {
        $builder = [System.UriBuilder]::new([uri]$BaseUrl)
        $builder.Port = $Port
        return $builder.Uri.AbsoluteUri.TrimEnd("/")
    } catch {
        return $BaseUrl
    }
}

function Get-CosyVoice3TtsBaseUrl {
    $baseUrl = Get-ConfiguredValueOrDefault -Key "COSYVOICE3_TTS_API_BASE_URL" -DefaultValue "http://127.0.0.1:30180"
    $mappedPort = Resolve-ContainerMappedPort -ContainerName "cosyvoice3-tts" -ContainerPort 8080
    if ($null -ne $mappedPort) {
        return Get-BaseUrlWithPort -BaseUrl $baseUrl -Port $mappedPort
    }
    return $baseUrl
}

function Get-MossTtsLocalBaseUrl {
    $baseUrl = Get-ConfiguredValueOrDefault -Key "MOSS_TTS_LOCAL_API_BASE_URL" -DefaultValue "http://127.0.0.1:30191"
    $mappedPort = Resolve-ContainerMappedPort -ContainerName "moss-tts-local" -ContainerPort 8080
    if ($null -ne $mappedPort) {
        return Get-BaseUrlWithPort -BaseUrl $baseUrl -Port $mappedPort
    }
    return $baseUrl
}

function Wait-RoughCutHttpServiceReady {
    param(
        [string]$ServiceName,
        [string]$BaseUrl,
        [string[]]$HealthPaths = @("/health"),
        [int]$TimeoutSec = 10
    )

    $trimmedBaseUrl = ([string]$BaseUrl).Trim().TrimEnd("/")
    if ([string]::IsNullOrWhiteSpace($trimmedBaseUrl)) {
        Write-Host "$ServiceName is not configured; skipping probe." -ForegroundColor DarkGray
        return $false
    }

    if (-not (Test-LocalHttpBaseUrl -BaseUrl $trimmedBaseUrl)) {
        Write-Host "$ServiceName is configured at $trimmedBaseUrl; skipping local process probe." -ForegroundColor DarkGray
        return $true
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        foreach ($path in $HealthPaths) {
            $normalizedPath = if ($path.StartsWith("/")) { $path } else { "/$path" }
            try {
                $response = Invoke-WebRequest -Uri "$trimmedBaseUrl$normalizedPath" -Method Get -TimeoutSec 3 -UseBasicParsing
                if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                    Write-Host "$ServiceName is healthy at $trimmedBaseUrl." -ForegroundColor Green
                    return $true
                }
            } catch {
            }
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    $port = Get-BaseUrlPort -BaseUrl $trimmedBaseUrl
    if ($null -ne $port -and (Test-PortListening -TestPort $port)) {
        Write-Host "$ServiceName port $port is open but health endpoint is not ready yet; RoughCut will retry on first demand." -ForegroundColor Yellow
        return $false
    }

    Write-Host "$ServiceName is currently stopped at $trimmedBaseUrl; RoughCut will start or retry the configured service on first demand." -ForegroundColor Yellow
    return $false
}

function Get-RoughCutStartupServiceProbes {
    $probes = @()

    if ((Get-ConfiguredTranscriptionProvider) -eq "local_http_asr") {
        $asrBaseUrl = Get-ConfiguredValue -Key "LOCAL_ASR_API_BASE_URL"
        $asrDisplayName = Get-ConfiguredValue -Key "LOCAL_ASR_DISPLAY_NAME"
        $label = if ($asrDisplayName) { "Local ASR ($asrDisplayName)" } else { "Local ASR" }
        $probes += [pscustomobject]@{
            Name = $label
            BaseUrl = $asrBaseUrl
            HealthPaths = @("/health")
            TimeoutSec = 5
        }
    }

    $probes += [pscustomobject]@{
        Name = "CosyVoice3 TTS"
        BaseUrl = Get-CosyVoice3TtsBaseUrl
        HealthPaths = @((Get-ConfiguredValueOrDefault -Key "COSYVOICE3_TTS_HEALTH_PATH" -DefaultValue "/health"))
        TimeoutSec = 5
    }

    $probes += [pscustomobject]@{
        Name = "MOSS-TTS Local"
        BaseUrl = Get-MossTtsLocalBaseUrl
        HealthPaths = @((Get-ConfiguredValueOrDefault -Key "MOSS_TTS_LOCAL_HEALTH_PATH" -DefaultValue "/health"))
        TimeoutSec = 5
    }

    if ((Get-ConfiguredAvatarProvider) -eq "heygem") {
        $probes += [pscustomobject]@{
            Name = "HeyGem API (external)"
            BaseUrl = Get-ConfiguredValue -Key "AVATAR_API_BASE_URL"
            HealthPaths = @("/easy/query?code=healthcheck", "/health")
            TimeoutSec = 2
        }
    }

    $voiceProvider = Get-ConfiguredVoiceProvider
    if ($voiceProvider -eq "indextts2") {
        $voiceBaseUrl = Get-ConfiguredValue -Key "VOICE_CLONE_API_BASE_URL"
        if (-not $voiceBaseUrl) {
            $voiceBaseUrl = Get-ConfiguredValue -Key "AVATAR_TRAINING_API_BASE_URL"
        }
        if (-not $voiceBaseUrl) {
            $configuredIndexTtsPort = Parse-PortValue -Value (Get-ConfiguredValue -Key "INDEXTTS2_API_PORT")
            if ($null -eq $configuredIndexTtsPort) {
                $configuredIndexTtsPort = Parse-PortValue -Value (Get-ConfiguredValue -Key "HEYGEM_TRAINING_API_PORT")
            }
            if ($null -ne $configuredIndexTtsPort) {
                $voiceBaseUrl = "http://127.0.0.1:$configuredIndexTtsPort"
            }
        }
        $probes += [pscustomobject]@{
            Name = "IndexTTS2"
            BaseUrl = $voiceBaseUrl
            HealthPaths = @("/health", "/v1/health")
            TimeoutSec = 10
        }
    } elseif ($voiceProvider -eq "runninghub") {
        $runningHubBaseUrl = Get-ConfiguredValue -Key "VOICE_CLONE_API_BASE_URL"
        if ($runningHubBaseUrl) {
            Write-Host "Voice provider runninghub is configured at $runningHubBaseUrl; skipping local TTS process probe." -ForegroundColor DarkGray
        }
    }

    return $probes
}

function Test-RoughCutConfiguredStartupServices {
    Write-Host "Checking configured external service endpoints..." -ForegroundColor Cyan
    foreach ($probe in @(Get-RoughCutStartupServiceProbes)) {
        Wait-RoughCutHttpServiceReady `
            -ServiceName $probe.Name `
            -BaseUrl $probe.BaseUrl `
            -HealthPaths $probe.HealthPaths `
            -TimeoutSec $probe.TimeoutSec | Out-Null
    }
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

    $candidateSource = $null
    if ($RequestedPort -gt 0) {
        $candidateSource = "$RequestedPort"
    } elseif ($env:ROUGHCUT_API_PORT) {
        $candidateSource = $env:ROUGHCUT_API_PORT
    } else {
        $dotEnvValue = Get-LocalDotEnvValue -Key "ROUGHCUT_API_PORT"
        $candidateSource = if ($dotEnvValue) { $dotEnvValue } else { "38471" }
    }

    $candidate = Parse-PortValue -Value $candidateSource
    if ($null -eq $candidate) {
        throw "Invalid ROUGHCUT_API_PORT value '$candidateSource'. Configure one canonical API port, normally 38471."
    }
    if ($UsedPorts.ContainsKey($candidate)) {
        throw "Canonical API port $candidate is already reserved by another RoughCut service. Stop that service or set ROUGHCUT_API_PORT explicitly; startup will not auto-switch API ports."
    }
    if (Is-TcpPortAvailable -TestPort $candidate) {
        $UsedPorts[$candidate] = $true
        return $candidate
    }

    $apiPattern = "roughcut(?:\.cli|\.exe`"?)\s+api\s+--host\s+(?:127\.0\.0\.1|0\.0\.0\.0)\s+--port\s+$candidate"
    if (@(Get-ProcessMatches -Pattern $apiPattern).Count -gt 0) {
        $UsedPorts[$candidate] = $true
        return $candidate
    }

    throw "Canonical API port $candidate is already in use by another process. Stop that process; RoughCut will not auto-switch API ports."
}

function Update-LocalServiceEnv {
    param(
        [int]$PostgresPort,
        [int]$RedisPort,
        [int]$MinioApiPort,
        [int]$MinioConsolePort,
        [int]$HeygemApiPort,
        [int]$HeygemTrainingPort,
        [int]$ApiPort,
        [bool]$IndexTtsEnabled = $false
    )

    $defaultHeygemRoot = "D:/duix_avatar_data/face2face"
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
    if ($IndexTtsEnabled) {
        $env:INDEXTTS2_API_PORT = "$HeygemTrainingPort"
    } else {
        Remove-Item "env:INDEXTTS2_API_PORT" -ErrorAction SilentlyContinue
    }
    $env:HEYGEM_SHARED_HOST_DIR = $heygemSharedRoot
    $env:HEYGEM_SHARED_ROOT = $heygemSharedRoot
    $voiceRoot = if ($env:HEYGEM_VOICE_ROOT -and -not [string]::IsNullOrWhiteSpace($env:HEYGEM_VOICE_ROOT)) {
        [System.IO.Path]::GetFullPath($env:HEYGEM_VOICE_ROOT).Replace('\\', '/')
    } else {
        "D:/duix_avatar_data/face2face/voice/data"
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
    Write-Host "Allocated ports -> PostgreSQL:$PostgresPort Redis:$RedisPort MinIO API:$MinioApiPort MinIO Console:$MinioConsolePort External HeyGem API:$HeygemApiPort Voice/Training:$HeygemTrainingPort API:$ApiPort" -ForegroundColor Cyan
}

function Get-ProcessMatches {
    param([string]$Pattern)

    if ([string]::IsNullOrWhiteSpace($Pattern) -or $Pattern.Trim() -in @(".*", "^.*$")) {
        throw "Refusing to match RoughCut processes with unsafe pattern: '$Pattern'."
    }

    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine `
            -and $_.CommandLine -match $Pattern `
            -and $_.Name -in @("python.exe", "pythonw.exe", "roughcut.exe", "celery.exe", "pwsh.exe", "powershell.exe", "node.exe", "cmd.exe")
    } | Sort-Object ProcessId)
}

function Get-RoughCutCommandMatchPattern {
    param([string]$Arguments)

    $escapedArguments = [regex]::Escape($Arguments) -replace "\\ ", "\s+"
    return "roughcut(?:\.cli|\.exe`"?)\s+$escapedArguments"
}

function Get-RoughCutApiCommandMatchPattern {
    return "roughcut(?:\.cli|\.exe`"?)\s+api\s+--host\s+(?:127\.0\.0\.1|0\.0\.0\.0)\s+--port"
}

function Get-RoughCutFrontendDevCommandMatchPattern {
    return 'pnpm(?:\.cmd|\.ps1)?[\s\S]*frontend[\s\S]*dev'
}

function Test-RoughCutLanIpv4Address {
    param([string]$Address)

    $parsed = $null
    if (-not [System.Net.IPAddress]::TryParse($Address, [ref]$parsed)) {
        return $false
    }
    if ($parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        return $false
    }

    $bytes = $parsed.GetAddressBytes()
    return $bytes[0] -eq 192 -and $bytes[1] -eq 168
}

function Get-RoughCutLanIpv4Addresses {
    $addresses = @()
    $getNetIPAddress = Get-Command Get-NetIPAddress -ErrorAction SilentlyContinue

    if ($null -ne $getNetIPAddress) {
        try {
            $addresses += @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object {
                $alias = [string]$_.InterfaceAlias
                $_.IPAddress `
                    -and (Test-RoughCutLanIpv4Address -Address $_.IPAddress) `
                    -and $_.IPAddress -ne "127.0.0.1" `
                    -and $_.IPAddress -notlike "169.254.*" `
                    -and $alias -notmatch "(?i)(Loopback|vEthernet|Docker|WSL|VMware|VirtualBox|Hyper-V)"
            } | ForEach-Object {
                $_.IPAddress
            })
        } catch {
            $addresses = @()
        }
    }

    if ($addresses.Count -eq 0) {
        try {
            $addresses += @([System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) | Where-Object {
                $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork `
                    -and (Test-RoughCutLanIpv4Address -Address $_.ToString()) `
                    -and $_.ToString() -ne "127.0.0.1" `
                    -and $_.ToString() -notlike "169.254.*"
            } | ForEach-Object {
                $_.ToString()
            })
        } catch {
            $addresses = @()
        }
    }

    return @($addresses | Where-Object {
        -not [string]::IsNullOrWhiteSpace($_)
    } | Sort-Object -Unique)
}

function Get-RoughCutApiLanUrls {
    param([int]$ApiPort)

    return @(Get-RoughCutLanIpv4Addresses | ForEach-Object {
        $address = $_
        "http://${address}:$ApiPort"
    })
}

function Get-RoughCutFrontendLanUrls {
    param([int]$FrontendPort)

    return @(Get-RoughCutLanIpv4Addresses | ForEach-Object {
        $address = $_
        "http://${address}:$FrontendPort"
    })
}

function Get-RoughCutDockerApiPort {
    $mappedPort = Resolve-ContainerMappedPort -ContainerName "roughcut-api-1" -ContainerPort 8000
    if ($null -ne $mappedPort) {
        return $mappedPort
    }

    $configuredPort = Parse-PortValue -Value $(if ($env:ROUGHCUT_API_PORT) { $env:ROUGHCUT_API_PORT } else { Get-LocalDotEnvValue -Key "ROUGHCUT_API_PORT" })
    if ($null -ne $configuredPort) {
        return $configuredPort
    }

    return 38471
}

function Stop-RoughCutProcess {
    param(
        [string]$Name,
        [string]$Pattern
    )

    $processes = @(Get-ProcessMatches -Pattern $Pattern)

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
    Stop-RoughCutProcess -Name "Frontend dev server" -Pattern (Get-RoughCutFrontendDevCommandMatchPattern)
    Stop-RoughCutProcess -Name "API" -Pattern (Get-RoughCutApiCommandMatchPattern)
    Stop-RoughCutProcess -Name "Orchestrator" -Pattern (Get-RoughCutCommandMatchPattern "orchestrator --poll-interval")
    Stop-RoughCutProcess -Name "Media worker" -Pattern (Get-RoughCutCommandMatchPattern "worker --queue media_queue")
    Stop-RoughCutProcess -Name "Media worker" -Pattern "celery -A roughcut\.pipeline\.celery_app:celery_app worker --queues=media_queue"
    Stop-RoughCutProcess -Name "LLM worker" -Pattern (Get-RoughCutCommandMatchPattern "worker --queue llm_queue")
    Stop-RoughCutProcess -Name "LLM worker" -Pattern "celery -A roughcut\.pipeline\.celery_app:celery_app worker --queues=llm_queue"
    Stop-RoughCutProcess -Name "Agent worker" -Pattern (Get-RoughCutCommandMatchPattern "worker --queue agent_queue")
    Stop-RoughCutProcess -Name "Agent worker" -Pattern "celery -A roughcut\.pipeline\.celery_app:celery_app worker --queues=agent_queue"
    Stop-RoughCutProcess -Name "Watcher" -Pattern (Get-RoughCutCommandMatchPattern "watcher")

    if ($StopDockerServices) {
        Write-Host "Stopping docker compose services..." -ForegroundColor Cyan
        $stopArgs = @("compose")
        if (Test-Path $PortsEnvFile) {
            $stopArgs += "--env-file"
            $stopArgs += $PortsEnvFile
        }
        $stopArgs += "stop"
        docker @stopArgs | Out-Host
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

function Start-RoughCutManagedProcessFromSpec {
    param([pscustomobject]$Spec)

    $startProcessSplat = @{
        FilePath = $Spec.FilePath
        ArgumentList = @($Spec.Arguments)
        WorkingDirectory = $Spec.WorkingDirectory
        PassThru = $true
        RedirectStandardOutput = $Spec.StdoutPath
        RedirectStandardError = $Spec.StderrPath
    }
    if ($Spec.HiddenWindow) {
        $startProcessSplat["WindowStyle"] = "Hidden"
    } else {
        $startProcessSplat["NoNewWindow"] = $true
    }

    $previousEnvironment = @{}
    foreach ($environmentEntry in $Spec.Environment.GetEnumerator()) {
        $environmentName = [string]$environmentEntry.Key
        $previousEnvironment[$environmentName] = [Environment]::GetEnvironmentVariable($environmentName, "Process")
        [Environment]::SetEnvironmentVariable($environmentName, [string]$environmentEntry.Value, "Process")
    }

    try {
        $process = Start-Process @startProcessSplat
    } finally {
        foreach ($environmentEntry in $previousEnvironment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable([string]$environmentEntry.Key, $environmentEntry.Value, "Process")
        }
    }

    [RoughCutJobObject]::Assign($script:ProcessJob, $process.Handle)
    return $process
}

function Add-RoughCutManagedProcess {
    param(
        [string]$Name,
        [System.Diagnostics.Process]$Process,
        [pscustomobject]$Spec
    )

    $script:ManagedProcesses += [pscustomobject]@{
        Name = $Name
        Process = $Process
        Spec = $Spec
        RestartCount = 0
        LastExitCode = $null
        RestartPending = $false
        NextRestartAt = $null
    }
}

function Schedule-RoughCutManagedProcessRestart {
    param([pscustomobject]$Entry)

    $Entry.RestartCount = [int]$Entry.RestartCount + 1
    $delaySeconds = [Math]::Min(30, [Math]::Max(1, [int][Math]::Pow(2, [Math]::Min($Entry.RestartCount - 1, 5))))
    $Entry.RestartPending = $true
    $Entry.NextRestartAt = (Get-Date).AddSeconds($delaySeconds)
    Write-Host "$($Entry.Name) will restart in $delaySeconds second(s) (restart #$($Entry.RestartCount))." -ForegroundColor Yellow
}

function Restart-RoughCutManagedProcess {
    param([pscustomobject]$Entry)

    $matches = @(Get-ProcessMatches -Pattern $Entry.Spec.MatchPattern)
    if ($matches.Count -gt 0) {
        $activeProcess = Get-Process -Id $matches[-1].ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $activeProcess) {
            $Entry.Process = $activeProcess
            $Entry.RestartPending = $false
            $Entry.NextRestartAt = $null
            Write-Host "$($Entry.Name) is already running again (PID $($activeProcess.Id)); supervisor reattached." -ForegroundColor Green
            return
        }
    }

    try {
        $process = Start-RoughCutManagedProcessFromSpec -Spec $Entry.Spec
        $Entry.Process = $process
        $Entry.RestartPending = $false
        $Entry.NextRestartAt = $null
        Write-Host "$($Entry.Name) restarted (PID $($process.Id))." -ForegroundColor Green
    } catch {
        Write-Host "Failed to restart $($Entry.Name): $($_.Exception.Message)" -ForegroundColor Red
        Schedule-RoughCutManagedProcessRestart -Entry $Entry
    }
}

function Start-RoughCutProcess {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [string]$MatchPattern,
        [string]$StdoutPath,
        [string]$StderrPath,
        [switch]$HiddenWindow
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
        $existingProcess = Get-Process -Id $matches[0].ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $existingProcess) {
            $spec = [pscustomobject]@{
                FilePath = $Python
                Arguments = @($Arguments)
                WorkingDirectory = $RepoRoot
                MatchPattern = $MatchPattern
                StdoutPath = $StdoutPath
                StderrPath = $StderrPath
                HiddenWindow = [bool]$HiddenWindow
                Environment = @{}
            }
            Add-RoughCutManagedProcess -Name $Name -Process $existingProcess -Spec $spec
        }
        Write-Host "$Name is already running. Supervisor attached." -ForegroundColor Yellow
        return
    }

    $spec = [pscustomobject]@{
        FilePath = $Python
        Arguments = @($Arguments)
        WorkingDirectory = $RepoRoot
        MatchPattern = $MatchPattern
        StdoutPath = $StdoutPath
        StderrPath = $StderrPath
        HiddenWindow = [bool]$HiddenWindow
        Environment = @{}
    }

    $process = Start-RoughCutManagedProcessFromSpec -Spec $spec
    Add-RoughCutManagedProcess -Name $Name -Process $process -Spec $spec

    Write-Host "$Name started (PID $($process.Id))." -ForegroundColor Green
}

function ConvertTo-CmdArgument {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) {
        return '""'
    }
    if ($Value -notmatch '[\s"&<>|^]') {
        return $Value
    }
    return '"' + ($Value.Replace('"', '\"')) + '"'
}

function Start-RoughCutPnpmProcess {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [string]$MatchPattern,
        [string]$StdoutPath,
        [string]$StderrPath,
        [hashtable]$Environment = @{}
    )

    if ($null -eq $Pnpm) {
        throw "pnpm is required to start $Name. Enable Corepack or install pnpm, then rerun."
    }

    $argumentText = ($Arguments | ForEach-Object { ConvertTo-CmdArgument -Value $_ }) -join " "
    $command = "pnpm $argumentText"
    $environmentCopy = @{}
    foreach ($entry in $Environment.GetEnumerator()) {
        $environmentCopy[[string]$entry.Key] = [string]$entry.Value
    }

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
        $existingProcess = Get-Process -Id $matches[0].ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $existingProcess) {
            $spec = [pscustomobject]@{
                FilePath = "cmd.exe"
                Arguments = @("/d", "/s", "/c", $command)
                WorkingDirectory = $RepoRoot
                MatchPattern = $MatchPattern
                StdoutPath = $StdoutPath
                StderrPath = $StderrPath
                HiddenWindow = $true
                Environment = $environmentCopy
            }
            Add-RoughCutManagedProcess -Name $Name -Process $existingProcess -Spec $spec
        }
        Write-Host "$Name is already running. Supervisor attached." -ForegroundColor Yellow
        return
    }

    $spec = [pscustomobject]@{
        FilePath = "cmd.exe"
        Arguments = @("/d", "/s", "/c", $command)
        WorkingDirectory = $RepoRoot
        MatchPattern = $MatchPattern
        StdoutPath = $StdoutPath
        StderrPath = $StderrPath
        HiddenWindow = $true
        Environment = $environmentCopy
    }

    $process = Start-RoughCutManagedProcessFromSpec -Spec $spec
    Add-RoughCutManagedProcess -Name $Name -Process $process -Spec $spec

    Write-Host "$Name started (PID $($process.Id))." -ForegroundColor Green
}

function Start-RoughCutFrontendDevServer {
    param(
        [int]$FrontendPort,
        [int]$ApiPort
    )

    @(Get-ProcessMatches -Pattern (Get-RoughCutFrontendDevCommandMatchPattern)) | ForEach-Object {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            Write-Host "Stopped existing frontend dev server (PID $($_.ProcessId)) so API proxy target is refreshed." -ForegroundColor Yellow
        } catch {
        }
    }

    Start-RoughCutPnpmProcess `
        -Name "Frontend dev server" `
        -Arguments @("--dir", "frontend", "dev") `
        -MatchPattern (Get-RoughCutFrontendDevCommandMatchPattern) `
        -StdoutPath (Join-Path $RepoRoot "logs\frontend-dev.out.log") `
        -StderrPath (Join-Path $RepoRoot "logs\frontend-dev.err.log") `
        -Environment @{
            VITE_API_PROXY_TARGET = "http://127.0.0.1:$ApiPort"
            VITE_DEV_HOST = "0.0.0.0"
            VITE_DEV_PORT = "$FrontendPort"
        }
}

function Start-RoughCutDockerFrontendDevSession {
    param([switch]$OpenBrowserAfterStart)

    $apiPort = Get-RoughCutDockerApiPort
    $usedPorts = @{ $apiPort = $true }
    $resolvedFrontendDevPort = Resolve-StandalonePort -EnvVarName "ROUGHCUT_FRONTEND_DEV_PORT" -PreferredPorts @($FrontendDevDefaultPort, 5174, 5175, 5176, 5177) -UsedPorts $usedPorts

    New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "logs") | Out-Null
    Start-RoughCutFrontendDevServer -FrontendPort $resolvedFrontendDevPort -ApiPort $apiPort

    $apiLocalUrl = "http://127.0.0.1:$apiPort"
    $frontendLocalUrl = "http://127.0.0.1:$resolvedFrontendDevPort"
    $frontendLanUrls = @(Get-RoughCutFrontendLanUrls -FrontendPort $resolvedFrontendDevPort)

    Write-Host ""
    Write-Host "Docker runtime is up; local frontend dev server is attached." -ForegroundColor Green
    Write-Host "Frontend URL: $frontendLocalUrl (Vite HMR enabled)" -ForegroundColor Green
    if ($frontendLanUrls.Count -eq 1) {
        Write-Host "Frontend LAN URL (192.168, Vite HMR): $($frontendLanUrls[0])" -ForegroundColor Green
    } elseif ($frontendLanUrls.Count -gt 1) {
        Write-Host "Frontend LAN URLs (192.168, Vite HMR):" -ForegroundColor Green
        foreach ($frontendLanUrl in $frontendLanUrls) {
            Write-Host "  $frontendLanUrl" -ForegroundColor Green
        }
    } else {
        Write-Host "Frontend LAN URL (192.168, Vite HMR): unavailable (no active 192.168 IPv4 address found)." -ForegroundColor DarkGray
    }
    Write-Host "API URL: $apiLocalUrl" -ForegroundColor Green
    Write-Host "Logs: .\logs\frontend-dev.out.log / .\logs\frontend-dev.err.log" -ForegroundColor DarkGray

    Wait-RoughCutHttpServiceReady -ServiceName "Frontend dev server" -BaseUrl $frontendLocalUrl -HealthPaths @("/") -TimeoutSec 20 | Out-Null
    if (Wait-ApiReady -TestPort $apiPort) {
        if ($OpenBrowserAfterStart) {
            Start-Process "$frontendLocalUrl/" | Out-Null
            Write-Host "GUI opened in your default browser." -ForegroundColor Green
        } else {
            Write-Host "API is ready. Open $frontendLocalUrl/ for hot-updating frontend development." -ForegroundColor Green
        }
    } else {
        Write-Host "API did not become ready in time. Check logs if the GUI does not open." -ForegroundColor Yellow
    }

    Wait-LauncherClose
}

function Start-RoughCutHostTelegramAgent {
    if (-not (Test-Path $EnsureTelegramAgentScript)) {
        Write-Host "Telegram agent ensure script not found: $EnsureTelegramAgentScript" -ForegroundColor Yellow
        return
    }

    $powerShellCommand = Get-PowerShellCommand
    Invoke-NativeCommandChecked -FilePath $powerShellCommand.Source -Arguments @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $EnsureTelegramAgentScript,
        "-Restart"
    ) -FailureMessage "Failed to start host Telegram agent"
}

function Stop-RoughCutHostTelegramAgent {
    if (-not (Test-Path $StopTelegramAgentScript)) {
        Write-Host "Telegram agent stop script not found: $StopTelegramAgentScript" -ForegroundColor Yellow
        return
    }

    $powerShellCommand = Get-PowerShellCommand
    Invoke-NativeCommandChecked -FilePath $powerShellCommand.Source -Arguments @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $StopTelegramAgentScript
    ) -FailureMessage "Failed to stop host Telegram agent"
}

function Get-RoughCutWorkerNodeName {
    param(
        [ValidateSet("media_queue", "llm_queue", "agent_queue")]
        [string]$Queue,
        [ValidateRange(1, 16)]
        [int]$Instance = 1
    )

    $suffix = switch ($Queue) {
        "media_queue" { "media-local" }
        "llm_queue" { "llm-local" }
        "agent_queue" { "agent-local" }
        default { "worker-local" }
    }
    if ($Instance -gt 1) {
        $suffix = "$suffix-$Instance"
    }
    return "$suffix@localhost"
}

function Test-RoughCutWorkerReady {
    param(
        [string]$WorkerNode,
        [string]$Queue
    )

    $pingOutput = Invoke-NativeCommandUnchecked -FilePath $Python -Arguments @(
        "-m", "celery",
        "-A", "roughcut.pipeline.celery_app:celery_app",
        "inspect", "ping",
        "-d", $WorkerNode,
        "--timeout=2",
        "--json"
    ) 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $pingOutput) {
        return $false
    }

    $queueOutput = Invoke-NativeCommandUnchecked -FilePath $Python -Arguments @(
        "-m", "celery",
        "-A", "roughcut.pipeline.celery_app:celery_app",
        "inspect", "active_queues",
        "-d", $WorkerNode,
        "--timeout=2",
        "--json"
    ) 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $queueOutput) {
        return $false
    }

    try {
        $queueMap = (($queueOutput -join [Environment]::NewLine) | ConvertFrom-Json)
    } catch {
        return $false
    }

    foreach ($property in $queueMap.PSObject.Properties) {
        foreach ($queueEntry in @($property.Value)) {
            if ($queueEntry.name -eq $Queue) {
                return $true
            }
        }
    }

    return $false
}

function Test-RoughCutWorkerReadyFromLogs {
    param(
        [string]$WorkerNode,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    $readyPatterns = @(
        [regex]::Escape("$WorkerNode ready."),
        [regex]::Escape(($WorkerNode -replace "@localhost$", "")) + ".*ready\."
    )

    foreach ($path in @($StdoutPath, $StderrPath)) {
        if (-not (Test-Path $path)) {
            continue
        }

        $lines = @(Get-Content $path -Tail 120 -ErrorAction SilentlyContinue)
        foreach ($line in $lines) {
            foreach ($pattern in $readyPatterns) {
                if ($line -match $pattern) {
                    return $true
                }
            }
        }
    }

    return $false
}

function Wait-RoughCutWorkerReady {
    param(
        [string]$Name,
        [string]$MatchPattern,
        [string]$WorkerNode,
        [string]$Queue,
        [string]$StdoutPath,
        [string]$StderrPath,
        [int]$TimeoutSec = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $matches = @(Get-ProcessMatches -Pattern $MatchPattern)
        if ($matches.Count -eq 0) {
            break
        }
        if (Test-RoughCutWorkerReady -WorkerNode $WorkerNode -Queue $Queue) {
            Write-Host "$Name is ready as $WorkerNode." -ForegroundColor Green
            return
        }
        if (Test-RoughCutWorkerReadyFromLogs -WorkerNode $WorkerNode -StdoutPath $StdoutPath -StderrPath $StderrPath) {
            Write-Host "$Name reported ready in logs as $WorkerNode." -ForegroundColor Green
            return
        }
        Start-Sleep -Milliseconds 750
    }

    $stdout = if (Test-Path $StdoutPath) { (Get-Content $StdoutPath -Tail 80 -ErrorAction SilentlyContinue) -join [Environment]::NewLine } else { "" }
    $stderr = if (Test-Path $StderrPath) { (Get-Content $StderrPath -Tail 80 -ErrorAction SilentlyContinue) -join [Environment]::NewLine } else { "" }
    $matches = @(Get-ProcessMatches -Pattern $MatchPattern)
    $processState = if ($matches.Count -gt 0) { "still running" } else { "not running" }
    if (-not [string]::IsNullOrWhiteSpace($stderr)) {
        throw "$Name failed to become ready ($processState). stderr:`n$stderr"
    }
    if (-not [string]::IsNullOrWhiteSpace($stdout)) {
        throw "$Name failed to become ready ($processState). stdout:`n$stdout"
    }
    throw "$Name failed to become ready ($processState)."
}

function Start-RoughCutWorkerProcess {
    param(
        [string]$Name,
        [ValidateSet("media_queue", "llm_queue", "agent_queue")]
        [string]$Queue,
        [string]$StdoutPath,
        [string]$StderrPath,
        [ValidateRange(1, 16)]
        [int]$Instance = 1
    )

    $workerNode = Get-RoughCutWorkerNodeName -Queue $Queue -Instance $Instance
    $matchPatterns = @(
        (Get-RoughCutCommandMatchPattern "worker --queue $Queue --pool solo --concurrency 1 --hostname $workerNode --without-gossip --without-mingle"),
        ("{0}.*{1}" -f [regex]::Escape("celery -A roughcut.pipeline.celery_app:celery_app worker --queues=$Queue"), [regex]::Escape($workerNode))
    )

    foreach ($pattern in $matchPatterns) {
        $matches = @(Get-ProcessMatches -Pattern $pattern)
        if ($matches.Count -gt 0) {
            if (Test-RoughCutWorkerReady -WorkerNode $workerNode -Queue $Queue) {
                Write-Host "$Name is already running and ready. Skipping." -ForegroundColor Yellow
                return
            }
            Stop-RoughCutProcess -Name $Name -Pattern $pattern
        }
    }

    $arguments = @(
        "-m", "roughcut.cli", "worker",
        "--queue", $Queue,
        "--pool", "solo",
        "--concurrency", "1",
        "--hostname", $workerNode,
        "--without-gossip",
        "--without-mingle"
    )
    $matchPattern = Get-RoughCutCommandMatchPattern "worker --queue $Queue --pool solo --concurrency 1 --hostname $workerNode --without-gossip --without-mingle"

    foreach ($logPath in @($StdoutPath, $StderrPath)) {
        $logDirectory = Split-Path -Parent $logPath
        if (-not [string]::IsNullOrWhiteSpace($logDirectory)) {
            New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
        }
        Set-Content -Path $logPath -Value "" -NoNewline
    }

    Start-RoughCutProcess `
        -Name $Name `
        -Arguments $arguments `
        -MatchPattern $matchPattern `
        -StdoutPath $StdoutPath `
        -StderrPath $StderrPath `
        -HiddenWindow

    Wait-RoughCutWorkerReady `
        -Name $Name `
        -MatchPattern $matchPattern `
        -WorkerNode $workerNode `
        -Queue $Queue `
        -StdoutPath $StdoutPath `
        -StderrPath $StderrPath
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

function Assert-LocalInfrastructureReady {
    param(
        [hashtable]$ServicePorts
    )

    $requiredServices = @(
        @{ Name = "PostgreSQL"; Port = $ServicePorts.Postgres }
        @{ Name = "Redis"; Port = $ServicePorts.Redis }
        @{ Name = "MinIO API"; Port = $ServicePorts.MinioApi }
    )

    $missingServices = @()
    foreach ($service in $requiredServices) {
        if (-not (Test-PortListening -TestPort $service.Port)) {
            $missingServices += "$($service.Name) (port $($service.Port))"
        }
    }

    if ($missingServices.Count -eq 0) {
        Write-Host "Required local infra endpoints are already reachable." -ForegroundColor Green
        if (Test-PortListening -TestPort $ServicePorts.MinioConsole) {
            Write-Host "MinIO Console is listening on port $($ServicePorts.MinioConsole)." -ForegroundColor Green
        } else {
            Write-Host "MinIO Console is not listening on port $($ServicePorts.MinioConsole); API access will still work." -ForegroundColor DarkGray
        }
        return
    }

    $detail = $missingServices -join ", "
    throw "Local mode does not start Docker infra automatically. Missing required services: $detail. Start them explicitly with './start_roughcut.bat infra' or provide equivalent local services before rerunning local mode."
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
    Write-Host "If a managed service exits, this launcher will automatically restart it." -ForegroundColor DarkGray
    Write-Host "Logs stay in .\logs\*.out.log / .\logs\*.err.log" -ForegroundColor DarkGray

    while ($true) {
        foreach ($entry in $script:ManagedProcesses) {
            try {
                if ($entry.Process.HasExited) {
                    if (-not $entry.RestartPending) {
                        $entry.LastExitCode = $entry.Process.ExitCode
                        Write-Host "$($entry.Name) exited with code $($entry.LastExitCode)." -ForegroundColor Yellow
                        Schedule-RoughCutManagedProcessRestart -Entry $entry
                    } elseif ((Get-Date) -ge $entry.NextRestartAt) {
                        Restart-RoughCutManagedProcess -Entry $entry
                    }
                }
            } catch {
                Write-Host "Supervisor check failed for $($entry.Name): $($_.Exception.Message)" -ForegroundColor Red
            }
        }
        Start-Sleep -Seconds 2
    }
}

if ($StopOnly) {
Stop-RoughCutServices -StopDockerServices:$StopDocker
Stop-RoughCutDockerWatch -ComposeMode all -SilentlyContinue
Stop-RoughCutHostTelegramAgent
Remove-LegacyHeygemMockContainer
    exit 0
}

if ($Mode -eq "install-autostart") {
    Install-RoughCutDockerAutostart
    exit 0
}

if ($Mode -eq "uninstall-autostart") {
    Uninstall-RoughCutDockerAutostart
    exit 0
}

if ($Mode -in @("runtime-watch", "full-watch")) {
    Start-RoughCutDockerWatchMode -WatchMode $Mode
    exit 0
}

if ($FrontendDev -and $NoFrontendDev) {
    throw "-FrontendDev and -NoFrontendDev cannot be used together."
}

if ($Mode -eq "runtime-down") {
    Stop-RoughCutComposeMode -ComposeMode "runtime"
    exit 0
}

if ($Mode -eq "full-down") {
    Stop-RoughCutHostTelegramAgent
    Stop-RoughCutComposeMode -ComposeMode "full"
    exit 0
}

if ($Mode -ne "local") {
    if ($Mode -in @("runtime", "full") -and $AutoDockerWatch) {
        $watchMode = if ($Mode -eq "full") { "full-watch" } else { "runtime-watch" }
        Start-RoughCutDockerWatchMode -WatchMode $watchMode
        exit 0
    }
    Start-RoughCutComposeMode -ComposeMode $Mode
    if ($Mode -eq "full") {
        Start-RoughCutHostTelegramAgent
    }
    if ($FrontendDev) {
        Start-RoughCutDockerFrontendDevSession -OpenBrowserAfterStart:$OpenBrowser
    }
    exit 0
}

Initialize-RoughCutEnvironment
Ensure-RoughCutFrontend

if ($SafeStart) {
    $NoWatcher = $true
    $NoOrchestrator = $true
    $NoWorkers = $true
    $OpenBrowser = $false
    Write-Host "Safe start enabled: watcher, orchestrator, workers, and browser auto-open are disabled." -ForegroundColor Yellow
}
if ($NoAutoResume) {
    $env:STARTUP_RECOVERY_ENABLED = "false"
    $env:STEP_STALE_RECOVERY_ENABLED = "false"
    Write-Host "Startup auto-resume and stale-step recovery disabled for this startup." -ForegroundColor Yellow
}
if ($NoWatchAutoDuty) {
    $env:WATCH_AUTO_DUTY_ENABLED = "false"
    $env:WATCH_AUTO_MERGE_ENABLED = "false"
    $env:WATCH_AUTO_ENQUEUE_ENABLED = "false"
    Write-Host "Watch auto duty, merge, and enqueue disabled for this startup." -ForegroundColor Yellow
}

Stop-RoughCutServices

Write-Host "Starting local RoughCut development stack..." -ForegroundColor Cyan
Write-Host "Default workflow: local Python + local frontend only." -ForegroundColor DarkGray
Write-Host "Docker infra is opt-in; local mode will not start containers for you." -ForegroundColor DarkGray
Write-Host "Docker runtime/full remain available as explicit containerized modes." -ForegroundColor DarkGray

$legacyDockerNames = @("fastcut-postgres-1", "fastcut-redis-1", "fastcut-minio-1")
Write-Host "Checking local infra endpoints..." -ForegroundColor Cyan
$usedPorts = @{}
$running = @()
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($null -ne $dockerCommand) {
    try {
        $running = & $dockerCommand.Source ps -a --format "{{.Names}}"
    } catch {
        Write-Host "Docker discovery failed; continuing with explicit local infra checks only." -ForegroundColor DarkGray
    }
} else {
    Write-Host "Docker CLI not found; continuing with explicit local infra checks only." -ForegroundColor DarkGray
}

    $legacy = @($legacyDockerNames | Where-Object { $_ -in $running })
    if ($legacy.Count -gt 0) {
        if (-not $CleanupLegacyDocker) {
            throw "Legacy FastCut containers detected: $($legacy -join ', '). Run 'docker rm -f $($legacy -join ' ')' or rerun with -CleanupLegacyDocker."
        }
        Write-Host "Removing legacy FastCut containers..." -ForegroundColor Yellow
        docker rm -f $legacy | Out-Host
    }

    $runtimeApiPort = Resolve-ContainerMappedPort -ContainerName "roughcut-api-1" -ContainerPort 8000
    if ($null -ne $runtimeApiPort) {
        $usedPorts[$runtimeApiPort] = $true
        Write-Host "Docker runtime API is already listening on port $runtimeApiPort; local API will use a different port." -ForegroundColor Yellow
    }

    $servicePorts = Resolve-PortSet -UsedPorts $usedPorts
    $indexTtsStartupProbeEnabled = Test-IndexTTS2StartupProbeEnabled
    $requestedApiPort = if ($PSBoundParameters.ContainsKey("Port")) { $Port } else { 0 }
    $resolvedApiPort = Resolve-ApiPort -UsedPorts $usedPorts -RequestedPort $requestedApiPort
    $resolvedFrontendDevPort = if ($NoFrontendDev) {
        0
    } else {
        Resolve-StandalonePort -EnvVarName "ROUGHCUT_FRONTEND_DEV_PORT" -PreferredPorts @($FrontendDevDefaultPort, 5174, 5175, 5176, 5177) -UsedPorts $usedPorts
    }

    Update-LocalServiceEnv -PostgresPort $servicePorts.Postgres -RedisPort $servicePorts.Redis -MinioApiPort $servicePorts.MinioApi -MinioConsolePort $servicePorts.MinioConsole -HeygemApiPort $servicePorts.HeygemApi -HeygemTrainingPort $servicePorts.HeygemTraining -ApiPort $resolvedApiPort -IndexTtsEnabled $indexTtsStartupProbeEnabled
    $Port = $resolvedApiPort

Assert-LocalInfrastructureReady -ServicePorts $servicePorts
Test-RoughCutConfiguredStartupServices

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
        -MatchPattern (Get-RoughCutCommandMatchPattern "watcher $WatchDir --language zh-CN") `
        -StdoutPath (Join-Path $RepoRoot "logs\watcher.out.log") `
        -StderrPath (Join-Path $RepoRoot "logs\watcher.err.log") `
        -HiddenWindow
}
Start-RoughCutProcess `
    -Name "API" `
    -Arguments @("-m", "roughcut.cli", "api", "--host", $ApiBindHost, "--port", "$Port") `
    -MatchPattern (Get-RoughCutCommandMatchPattern "api --host $ApiBindHost --port $Port") `
    -StdoutPath (Join-Path $RepoRoot "logs\api.out.log") `
    -StderrPath (Join-Path $RepoRoot "logs\api.err.log") `
    -HiddenWindow
if ($NoFrontendDev) {
    Write-Host "Frontend dev server disabled; API will serve frontend/dist." -ForegroundColor Yellow
} else {
    Start-RoughCutFrontendDevServer -FrontendPort $resolvedFrontendDevPort -ApiPort $Port
}
if ($NoOrchestrator) {
    Write-Host "Orchestrator disabled for this startup." -ForegroundColor Yellow
} else {
    Start-RoughCutProcess `
        -Name "Orchestrator" `
        -Arguments @("-m", "roughcut.cli", "orchestrator", "--poll-interval", "2") `
        -MatchPattern (Get-RoughCutCommandMatchPattern "orchestrator --poll-interval 2") `
        -StdoutPath (Join-Path $RepoRoot "logs\orchestrator.out.log") `
        -StderrPath (Join-Path $RepoRoot "logs\orchestrator.err.log") `
        -HiddenWindow
}
if ($NoWorkers) {
    Write-Host "Workers disabled for this startup." -ForegroundColor Yellow
} else {
    for ($mediaWorkerIndex = 1; $mediaWorkerIndex -le $MediaWorkerCount; $mediaWorkerIndex++) {
        $mediaLogSuffix = if ($mediaWorkerIndex -eq 1) { "" } else { "-$mediaWorkerIndex" }
        Start-RoughCutWorkerProcess `
            -Name "Media worker $mediaWorkerIndex" `
            -Queue "media_queue" `
            -StdoutPath (Join-Path $RepoRoot "logs\media-worker$mediaLogSuffix.out.log") `
            -StderrPath (Join-Path $RepoRoot "logs\media-worker$mediaLogSuffix.err.log") `
            -Instance $mediaWorkerIndex
    }
    for ($llmWorkerIndex = 1; $llmWorkerIndex -le $LlmWorkerCount; $llmWorkerIndex++) {
        $llmLogSuffix = if ($llmWorkerIndex -eq 1) { "" } else { "-$llmWorkerIndex" }
        Start-RoughCutWorkerProcess `
            -Name "LLM worker $llmWorkerIndex" `
            -Queue "llm_queue" `
            -StdoutPath (Join-Path $RepoRoot "logs\llm-worker$llmLogSuffix.out.log") `
            -StderrPath (Join-Path $RepoRoot "logs\llm-worker$llmLogSuffix.err.log") `
            -Instance $llmWorkerIndex
    }
    Start-RoughCutWorkerProcess `
        -Name "Agent worker" `
        -Queue "agent_queue" `
        -StdoutPath (Join-Path $RepoRoot "logs\agent-worker.out.log") `
        -StderrPath (Join-Path $RepoRoot "logs\agent-worker.err.log")
}

$apiLocalUrl = "http://127.0.0.1:$Port"
$frontendLocalUrl = if ($NoFrontendDev) { $apiLocalUrl } else { "http://127.0.0.1:$resolvedFrontendDevPort" }
$apiLanUrls = @(Get-RoughCutApiLanUrls -ApiPort $Port)
$frontendLanUrls = @(if ($NoFrontendDev) { @() } else { Get-RoughCutFrontendLanUrls -FrontendPort $resolvedFrontendDevPort })

Write-Host ""
Write-Host "RoughCut started." -ForegroundColor Green
if (-not $NoFrontendDev) {
    Write-Host "Frontend URL: $frontendLocalUrl (Vite HMR enabled)" -ForegroundColor Green
    if ($frontendLanUrls.Count -eq 1) {
        Write-Host "Frontend LAN URL (192.168, Vite HMR): $($frontendLanUrls[0])" -ForegroundColor Green
    } elseif ($frontendLanUrls.Count -gt 1) {
        Write-Host "Frontend LAN URLs (192.168, Vite HMR):" -ForegroundColor Green
        foreach ($frontendLanUrl in $frontendLanUrls) {
            Write-Host "  $frontendLanUrl" -ForegroundColor Green
        }
    } else {
        Write-Host "Frontend LAN URL (192.168, Vite HMR): unavailable (no active 192.168 IPv4 address found)." -ForegroundColor DarkGray
    }
}
Write-Host "API URL: $apiLocalUrl" -ForegroundColor Green
if ($apiLanUrls.Count -eq 1) {
    Write-Host "LAN URL (192.168): $($apiLanUrls[0])" -ForegroundColor Green
} elseif ($apiLanUrls.Count -gt 1) {
    Write-Host "LAN URLs (192.168):" -ForegroundColor Green
    foreach ($apiLanUrl in $apiLanUrls) {
        Write-Host "  $apiLanUrl" -ForegroundColor Green
    }
} else {
    Write-Host "LAN URL (192.168): unavailable (no active 192.168 IPv4 address found)." -ForegroundColor DarkGray
}
Write-Host "Logs: .\logs\*.out.log / .\logs\*.err.log" -ForegroundColor DarkGray

if (Wait-ApiReady -TestPort $Port) {
    if ($OpenBrowser) {
        Start-Process "$frontendLocalUrl/" | Out-Null
        Write-Host "GUI opened in your default browser." -ForegroundColor Green
    } else {
        if ($NoFrontendDev) {
            Write-Host "API is ready. Open $apiLocalUrl/ manually when needed." -ForegroundColor Green
        } else {
            Write-Host "API is ready. Open $frontendLocalUrl/ for hot-updating frontend development." -ForegroundColor Green
        }
    }
} else {
    Write-Host "API did not become ready in time. Check logs if the GUI does not open." -ForegroundColor Yellow
}

Wait-LauncherClose
