param(
    [string]$NodePath = "",
    [string]$ScriptPath = "",
    [string]$CdpUrl = "http://127.0.0.1:9222",
    [string]$Browser = "chrome",
    [string]$UserDataDir = "",
    [string]$ProfileDirectory = "",
    [int]$Port = 49310,
    [bool]$AllowTabAutocreate = $false,
    [switch]$EnableLivePublish,
    [switch]$StopExisting,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-DefaultPublicationUserDataDir {
    $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR", "Process")
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR", "User")
    }
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR", "Machine")
    }
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        return $configured.Trim()
    }
    $chromeUserDataDir = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"
    if (Test-Path -LiteralPath $chromeUserDataDir) {
        return $chromeUserDataDir
    }
    return (Join-Path $repoRoot "data\runtime\publication-browser-profile-stable\chrome-user-data")
}

function Get-DefaultPublicationProfileDirectory {
    $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_PROFILE_DIRECTORY", "Process")
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_PROFILE_DIRECTORY", "User")
    }
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_PROFILE_DIRECTORY", "Machine")
    }
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        return $configured.Trim()
    }
    return "Profile 2"
}
if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
    $ScriptPath = Join-Path $repoRoot "scripts\publication_browser_agent_service.mjs"
}
if ([string]::IsNullOrWhiteSpace($NodePath)) {
    $nodeCommand = Get-Command node -ErrorAction Stop
    $NodePath = $nodeCommand.Source
}

if ([string]::IsNullOrWhiteSpace($UserDataDir)) {
    $UserDataDir = Get-DefaultPublicationUserDataDir
}
if ([string]::IsNullOrWhiteSpace($ProfileDirectory)) {
    $ProfileDirectory = Get-DefaultPublicationProfileDirectory
}
if (-not (Test-Path -LiteralPath $NodePath)) {
    throw "Node executable not found: $NodePath"
}
if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Browser agent entry script not found: $ScriptPath"
}

function Get-PublicationBrowserAgentProcess {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "node.exe" -and $_.CommandLine -match "publication_browser_agent_service\.mjs"
    }
}

function Get-PublicationBrowserAgentPortOwner {
    param(
        [int]$ListenPort
    )

    $connection = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $connection) {
        return $null
    }
    return [int]$connection.OwningProcess
}

function Wait-PublicationBrowserAgentPortReleased {
    param(
        [int]$ListenPort,
        [int]$TimeoutMs = 10000
    )

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    do {
        $ownerProcessId = Get-PublicationBrowserAgentPortOwner -ListenPort $ListenPort
        if (-not $ownerProcessId) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)

    $ownerProcessId = Get-PublicationBrowserAgentPortOwner -ListenPort $ListenPort
    if ($ownerProcessId) {
        throw "Publication browser-agent port $ListenPort is still occupied by PID $ownerProcessId after waiting ${TimeoutMs}ms."
    }
}

if ($StopExisting) {
    $existingByCommandLine = @(Get-PublicationBrowserAgentProcess)
    $existingByPort = @()
    $portOwnerProcessId = Get-PublicationBrowserAgentPortOwner -ListenPort $Port
    if ($portOwnerProcessId) {
        $existingByPort = @(Get-CimInstance Win32_Process -Filter "ProcessId = $portOwnerProcessId")
    }

    $existing = @($existingByCommandLine + $existingByPort | Group-Object ProcessId | ForEach-Object { $_.Group[0] })
    foreach ($process in $existing) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        } catch {
            throw "Failed to stop existing browser-agent PID $($process.ProcessId): $($_.Exception.Message)"
        }
    }

    Wait-PublicationBrowserAgentPortReleased -ListenPort $Port
}

$stdoutLog = Join-Path $repoRoot "artifacts\publication-agent-live.log"
$stderrLog = Join-Path $repoRoot "artifacts\publication-agent-live.err.log"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $stdoutLog) | Out-Null
Clear-Content -Path $stdoutLog -ErrorAction SilentlyContinue
Clear-Content -Path $stderrLog -ErrorAction SilentlyContinue

$environmentMap = [ordered]@{
    PUBLICATION_BROWSER_AGENT_PORT = "$Port"
    PUBLICATION_BROWSER_CDP_URL = $CdpUrl.Trim()
    PUBLICATION_BROWSER = $Browser.Trim()
    PUBLICATION_BROWSER_USER_DATA_DIR = $UserDataDir.Trim()
    PUBLICATION_BROWSER_PROFILE_DIRECTORY = $ProfileDirectory.Trim()
    PUBLICATION_BROWSER_ALLOW_TAB_AUTOCREATE = $AllowTabAutocreate.ToString().ToLowerInvariant()
    PUBLICATION_LIVE_PUBLISH_ENABLED = $(if ($EnableLivePublish) { "true" } else { "false" })
}

if ($DryRun) {
    [pscustomobject]@{
        node_path = $NodePath
        script_path = $ScriptPath
        working_directory = $repoRoot
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
        environment = $environmentMap
        note = "Default launches bind to the stable dedicated publication profile root unless ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR / PROFILE_DIRECTORY overrides are set."
    } | ConvertTo-Json -Depth 6
    return
}

$cmdSegments = @()
foreach ($environmentEntry in $environmentMap.GetEnumerator()) {
    $cmdSegments += ('set "{0}={1}"' -f [string]$environmentEntry.Key, [string]$environmentEntry.Value)
}
$cmdSegments += ('cd /d "{0}"' -f $repoRoot)
$cmdSegments += ('"{0}" "{1}"' -f $NodePath, $ScriptPath)
$wrapperScript = $cmdSegments -join ' && '

$process = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList @('/d', '/c', $wrapperScript) `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru

[pscustomobject]@{
    pid = $process.Id
    stdout_log = $stdoutLog
    stderr_log = $stderrLog
    environment = $environmentMap
} | ConvertTo-Json -Depth 6
