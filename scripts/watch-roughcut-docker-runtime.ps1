[CmdletBinding()]
param(
    [ValidateSet("runtime", "full")]
    [string]$ComposeMode = "runtime",

    [string]$DockerPythonExtras = "",

    [int]$DebounceMilliseconds = 2000,

    [switch]$NoBuild,

    [switch]$RunOnce,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$sessionScript = Join-Path $repoRoot "scripts/run-roughcut-docker-refresh-session.ps1"
$lockDir = Join-Path $repoRoot "logs"
$lockPath = Join-Path $lockDir ("docker-watch-{0}.lock" -f $ComposeMode)
$subscriptions = @()
$watchers = @()
$pendingPaths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$pendingSince = $null
$retryNotBefore = $null

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

function Resolve-WatchLockState {
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
        throw "RoughCut docker watch is already running for $ComposeMode. Lock: $Path`n$(Format-RoughCutLockRecord -LockRecord $lockRecord)"
    }

    Write-Warning ("Removing stale RoughCut docker watch lock for {0}: {1}" -f $ComposeMode, (Format-RoughCutLockRecord -LockRecord $lockRecord))
    Remove-Item $Path -Force -ErrorAction SilentlyContinue
}

function Test-RelevantRoughCutWorkspacePath {
    param([string]$RelativePath)

    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        return $false
    }

    $normalized = $RelativePath.Replace("/", "\")
    while ($normalized.StartsWith(".\") -or $normalized.StartsWith("\")) {
        $normalized = $normalized.Substring(1)
    }
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return $false
    }

    $ignoredPrefixes = @(
        ".codex\",
        ".codex-tmp\",
        ".git\",
        ".pytest_cache\",
        ".ruff_cache\",
        ".venv\",
        "data\",
        "docs\",
        "logs\",
        "node_modules\",
        "watch\"
    )
    foreach ($prefix in $ignoredPrefixes) {
        if ($normalized.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $false
        }
    }

    $ignoredFragments = @(
        "\__pycache__\",
        "\node_modules\",
        "\dist\"
    )
    foreach ($fragment in $ignoredFragments) {
        if ($normalized.IndexOf($fragment, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $false
        }
    }

    $allowedFiles = @(
        ".env",
        ".env.example",
        "Dockerfile",
        "README.md",
        "alembic.ini",
        "docker-compose.infra.yml",
        "docker-compose.runtime.yml",
        "docker-compose.automation.yml",
        "docker-compose.yml",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "pyproject.toml",
        "start_roughcut.bat",
        "start_roughcut.ps1",
        "uv.lock"
    )
    foreach ($fileName in $allowedFiles) {
        if ($normalized.Equals($fileName, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    $allowedPrefixes = @(
        "frontend\",
        "src\"
    )
    $matchesPrefix = $false
    foreach ($prefix in $allowedPrefixes) {
        if ($normalized.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $matchesPrefix = $true
            break
        }
    }
    if (-not $matchesPrefix) {
        return $false
    }

    $allowedExtensions = @(
        ".css",
        ".html",
        ".js",
        ".json",
        ".md",
        ".ps1",
        ".py",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".yaml",
        ".yml"
    )
    $extension = [System.IO.Path]::GetExtension($normalized)
    if ($allowedExtensions -contains $extension.ToLowerInvariant()) {
        return $true
    }

    return $false
}

function Get-RelativeRoughCutPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    $resolvedRoot = [System.IO.Path]::GetFullPath($repoRoot)
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $relative = [System.IO.Path]::GetRelativePath($resolvedRoot, $resolvedPath)
    return $relative.Replace("/", "\")
}

function Invoke-RefreshSession {
    param([string[]]$ChangedPaths)

    $sessionParams = @{
        ComposeMode = $ComposeMode
        ChangedPaths = $ChangedPaths
        DockerPythonExtras = $DockerPythonExtras
    }
    if ($NoBuild) {
        $sessionParams.NoBuild = $true
    }
    if ($DryRun) {
        $sessionParams.DryRun = $true
    }

    $hasFailure = $false
    $status = "success"
    try {
        $scriptOutput = @(& $sessionScript @sessionParams 2>&1)
        foreach ($entry in $scriptOutput) {
            if ($entry -is [System.Management.Automation.ErrorRecord]) {
                $hasFailure = $true
                $message = $entry.ToString()
                if ($message -match "\[DEFERRED\]") {
                    $status = "deferred"
                    Write-Host (" [WARN] {0}" -f $message)
                } else {
                    $status = "failed"
                    Write-Host (" [ERROR] {0}" -f $message)
                }
            } elseif ($null -ne $entry) {
                Write-Host $entry
            }
        }
    } catch {
        $hasFailure = $true
        $message = $_.Exception.Message
        if ($message -match "\[DEFERRED\]") {
            $status = "deferred"
            Write-Host (" [WARN] {0}" -f $message)
        } else {
            $status = "failed"
            Write-Host (" [ERROR] {0}" -f $message)
        }
        if ($_.Exception.InnerException) {
            Write-Host (" [ERROR] Inner exception: {0}" -f $_.Exception.InnerException.Message)
        }
        return [pscustomobject]@{
            ExitCode = 1
            Status = $status
        }
    }

    if ($hasFailure) {
        return [pscustomobject]@{
            ExitCode = 1
            Status = $status
        }
    }

    return [pscustomobject]@{
        ExitCode = 0
        Status = $status
    }
}

if ($RunOnce) {
    $refreshResult = Invoke-RefreshSession -ChangedPaths @("<manual-run>")
    exit $refreshResult.ExitCode
}

New-Item -ItemType Directory -Force -Path $lockDir | Out-Null

Resolve-WatchLockState -Path $lockPath -ScriptName "watch-roughcut-docker-runtime.ps1"

$lockContent = @(
    "pid=$PID"
    "started_at_utc=$([DateTime]::UtcNow.ToString("o"))"
    "compose_mode=$ComposeMode"
    "script=watch-roughcut-docker-runtime.ps1"
    "workspace_root=$repoRoot"
) -join [Environment]::NewLine
Set-Content -Path $lockPath -Value $lockContent -Encoding UTF8

$watcher = [System.IO.FileSystemWatcher]::new($repoRoot)
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]'FileName, DirectoryName, LastWrite, CreationTime'
$watcher.EnableRaisingEvents = $true
$watchers += $watcher

$eventActions = @("Changed", "Created", "Deleted", "Renamed")
foreach ($action in $eventActions) {
    $subscriptions += Register-ObjectEvent -InputObject $watcher -EventName $action -SourceIdentifier ("roughcut-docker-watch-{0}" -f $action) -MessageData $action
}
$subscriptions += Register-ObjectEvent -InputObject $watcher -EventName "Error" -SourceIdentifier "roughcut-docker-watch-Error" -MessageData "Error"

Write-Host ""
Write-Host " =========================================="
Write-Host "  RoughCut Docker Auto-Refresh Loop"
Write-Host " =========================================="
Write-Host (" [INFO] Compose Mode      : {0}" -f $ComposeMode)
Write-Host (" [INFO] Debounce (ms)     : {0}" -f $DebounceMilliseconds)
Write-Host (" [INFO] Build Image       : {0}" -f $(-not $NoBuild))
Write-Host (" [INFO] Python Extras     : {0}" -f $(if ([string]::IsNullOrWhiteSpace($DockerPythonExtras)) { "<none>" } else { $DockerPythonExtras }))
Write-Host (" [INFO] Workspace Root    : {0}" -f $repoRoot)
Write-Host ""
Write-Host " [WARN] This loop rebuilds and recreates runtime containers."
Write-Host " [WARN] Use it for Docker-based development, not for a busy always-on production queue."
Write-Host ""

try {
    while ($true) {
        $event = Wait-Event -Timeout 1
        if ($null -ne $event) {
            if ($event.SourceEventArgs -is [System.IO.ErrorEventArgs]) {
                $watchException = $event.SourceEventArgs.GetException()
                Write-Warning ("File watcher error: {0}" -f $watchException.Message)
                if ($null -ne $watchException.InnerException) {
                    Write-Warning ("File watcher inner error: {0}" -f $watchException.InnerException.Message)
                }
                Remove-Event -EventIdentifier $event.EventIdentifier
                continue
            }

            $eventPath = $event.SourceEventArgs.FullPath
            $relativePath = Get-RelativeRoughCutPath -Path $eventPath
            if (Test-RelevantRoughCutWorkspacePath -RelativePath $relativePath) {
                $null = $pendingPaths.Add($relativePath)
                $pendingSince = Get-Date
                $retryNotBefore = $null
                Write-Host (" [INFO] Queued change: {0}" -f $relativePath)
            }
            Remove-Event -EventIdentifier $event.EventIdentifier
            continue
        }

        if ($pendingPaths.Count -eq 0 -or $null -eq $pendingSince) {
            continue
        }

        $elapsed = ((Get-Date) - $pendingSince).TotalMilliseconds
        if ($elapsed -lt $DebounceMilliseconds) {
            continue
        }
        if ($null -ne $retryNotBefore -and (Get-Date) -lt $retryNotBefore) {
            continue
        }

        $changedBatch = @($pendingPaths)
        $pendingPaths.Clear()
        $pendingSince = $null

        Write-Host (" [INFO] Refreshing Docker {0} after {1} change(s)" -f $ComposeMode, $changedBatch.Count)
        $refreshResult = Invoke-RefreshSession -ChangedPaths $changedBatch
        if ($refreshResult.ExitCode -ne 0) {
            foreach ($path in $changedBatch) {
                $null = $pendingPaths.Add($path)
            }
            if ($pendingPaths.Count -gt 0) {
                $pendingSince = Get-Date
                $retryDelaySeconds = if ($refreshResult.Status -eq "deferred") { 30 } else { 5 }
                $retryNotBefore = (Get-Date).AddSeconds($retryDelaySeconds)
                if ($refreshResult.Status -eq "deferred") {
                    Write-Warning ("Docker auto-refresh deferred because active work is still running. Retrying in {0} seconds." -f $retryDelaySeconds)
                }
            }
            Write-Warning ("Docker auto-refresh failed with exit code {0}" -f $refreshResult.ExitCode)
            Write-Warning ("Pending changes retained for retry: {0}" -f ($changedBatch -join ", "))
        } else {
            $retryNotBefore = $null
            Write-Host " [OK] Docker auto-refresh complete"
        }
    }
} finally {
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
    foreach ($subscription in $subscriptions) {
        if ($null -ne $subscription) {
            Unregister-Event -SubscriptionId $subscription.Id -ErrorAction SilentlyContinue
        }
    }
    foreach ($watcherItem in $watchers) {
        if ($null -ne $watcherItem) {
            $watcherItem.EnableRaisingEvents = $false
            $watcherItem.Dispose()
        }
    }
}
