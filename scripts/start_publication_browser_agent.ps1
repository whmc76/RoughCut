param(
    [string]$NodePath = "",
    [string]$ScriptPath = "",
    [string]$CdpUrl = "http://127.0.0.1:9222",
    [string]$Browser = "chrome",
    [string]$UserDataDir,
    [string]$ProfileDirectory,
    [int]$Port = 49310,
    [bool]$AllowTabAutocreate = $false,
    [switch]$EnableLivePublish,
    [switch]$StopExisting,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
    $ScriptPath = Join-Path $repoRoot "scripts\publication_browser_agent_service.mjs"
}
if ([string]::IsNullOrWhiteSpace($NodePath)) {
    $nodeCommand = Get-Command node -ErrorAction Stop
    $NodePath = $nodeCommand.Source
}

if ([string]::IsNullOrWhiteSpace($UserDataDir)) {
    throw "Missing -UserDataDir. Real publication must bind to an explicit Chrome profile root."
}
if ([string]::IsNullOrWhiteSpace($ProfileDirectory)) {
    throw "Missing -ProfileDirectory. Real publication must bind to an explicit Chrome profile directory."
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

if ($StopExisting) {
    $existing = @(Get-PublicationBrowserAgentProcess)
    foreach ($process in $existing) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        } catch {
            throw "Failed to stop existing browser-agent PID $($process.ProcessId): $($_.Exception.Message)"
        }
    }
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
        note = "Use process-scoped environment injection before Start-Process so profile binding and live publish flags reach the browser-agent child process."
    } | ConvertTo-Json -Depth 6
    return
}

$previousEnvironment = @{}
foreach ($environmentEntry in $environmentMap.GetEnumerator()) {
    $environmentName = [string]$environmentEntry.Key
    $previousEnvironment[$environmentName] = [Environment]::GetEnvironmentVariable($environmentName, "Process")
    [Environment]::SetEnvironmentVariable($environmentName, [string]$environmentEntry.Value, "Process")
}

try {
    $process = Start-Process `
        -FilePath $NodePath `
        -ArgumentList @($ScriptPath) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog
} finally {
    foreach ($environmentEntry in $previousEnvironment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable([string]$environmentEntry.Key, $environmentEntry.Value, "Process")
    }
}

[pscustomobject]@{
    pid = $process.Id
    stdout_log = $stdoutLog
    stderr_log = $stderrLog
    environment = $environmentMap
} | ConvertTo-Json -Depth 6
