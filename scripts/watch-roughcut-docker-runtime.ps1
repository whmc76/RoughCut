[CmdletBinding()]
param(
    [ValidateSet("runtime", "full")]
    [string]$ComposeMode = "runtime",

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

function Get-WatchLockProcessId {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $null
    }

    foreach ($line in (Get-Content $Path -ErrorAction SilentlyContinue)) {
        if ($line -match "^pid=(\d+)$") {
            return [int]$Matches[1]
        }
    }

    return $null
}

function Test-WatchProcessActive {
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
    }
    if ($NoBuild) {
        $sessionParams.NoBuild = $true
    }
    if ($DryRun) {
        $sessionParams.DryRun = $true
    }

    try {
        $scriptOutput = @(& $sessionScript @sessionParams 2>&1)
        foreach ($entry in $scriptOutput) {
            if ($entry -is [System.Management.Automation.ErrorRecord]) {
                Write-Host ($entry.ToString())
            } elseif ($null -ne $entry) {
                Write-Host $entry
            }
        }
        return 0
    } catch {
        Write-Host $_
        return 1
    }
}

if ($RunOnce) {
    $exitCode = Invoke-RefreshSession -ChangedPaths @("<manual-run>")
    exit $exitCode
}

New-Item -ItemType Directory -Force -Path $lockDir | Out-Null

if (Test-Path $lockPath) {
    $existingPid = Get-WatchLockProcessId -Path $lockPath
    if ($null -ne $existingPid -and (Test-WatchProcessActive -ProcessId $existingPid)) {
        throw "RoughCut docker watch is already running for $ComposeMode. Lock: $lockPath"
    }
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
}

$lockContent = @(
    "pid=$PID"
    "started_at_utc=$([DateTime]::UtcNow.ToString("o"))"
    "compose_mode=$ComposeMode"
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

Write-Host ""
Write-Host " =========================================="
Write-Host "  RoughCut Docker Auto-Refresh Loop"
Write-Host " =========================================="
Write-Host (" [INFO] Compose Mode      : {0}" -f $ComposeMode)
Write-Host (" [INFO] Debounce (ms)     : {0}" -f $DebounceMilliseconds)
Write-Host (" [INFO] Build Image       : {0}" -f $(-not $NoBuild))
Write-Host (" [INFO] Workspace Root    : {0}" -f $repoRoot)
Write-Host ""
Write-Host " [WARN] This loop rebuilds and recreates runtime containers."
Write-Host " [WARN] Use it for Docker-based development, not for a busy always-on production queue."
Write-Host ""

try {
    while ($true) {
        $event = Wait-Event -Timeout 1
        if ($null -ne $event) {
            $eventPath = $event.SourceEventArgs.FullPath
            $relativePath = Get-RelativeRoughCutPath -Path $eventPath
            if (Test-RelevantRoughCutWorkspacePath -RelativePath $relativePath) {
                $null = $pendingPaths.Add($relativePath)
                $pendingSince = Get-Date
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

        $changedBatch = @($pendingPaths)
        $pendingPaths.Clear()
        $pendingSince = $null

        Write-Host (" [INFO] Refreshing Docker {0} after {1} change(s)" -f $ComposeMode, $changedBatch.Count)
        $exitCode = Invoke-RefreshSession -ChangedPaths $changedBatch
        if ($exitCode -ne 0) {
            Write-Warning ("Docker auto-refresh failed with exit code {0}" -f $exitCode)
        } else {
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
