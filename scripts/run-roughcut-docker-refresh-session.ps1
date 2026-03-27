[CmdletBinding()]
param(
    [ValidateSet("runtime", "full")]
    [string]$ComposeMode = "runtime",

    [string[]]$ChangedPaths = @(),

    [switch]$NoBuild,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$lockDir = Join-Path $repoRoot "logs"
$lockPath = Join-Path $lockDir ("docker-refresh-{0}.lock" -f $ComposeMode)

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

New-Item -ItemType Directory -Force -Path $lockDir | Out-Null

if (Test-Path $lockPath) {
    $lockPayload = Get-Content $lockPath -Raw -ErrorAction SilentlyContinue
    throw "RoughCut docker refresh session is already running for $ComposeMode. Lock: $lockPath`n$lockPayload"
}

$lockContent = @(
    "pid=$PID"
    "started_at_utc=$([DateTime]::UtcNow.ToString("o"))"
    "compose_mode=$ComposeMode"
) -join [Environment]::NewLine
Set-Content -Path $lockPath -Value $lockContent -Encoding UTF8

try {
    Set-Location $repoRoot

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

    $upArgs = @("up", "-d")
    if (-not $NoBuild) {
        $upArgs += "--build"
    }
    $upArgs += "--force-recreate"
    $upArgs += "--remove-orphans"
    $upArgs += Get-RoughCutRefreshServices -Mode $ComposeMode

    Invoke-Step ("Refresh Docker {0} runtime via docker compose {1}" -f $ComposeMode, ($upArgs -join " ")) {
        docker @composeArgs @upArgs
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose refresh failed for $ComposeMode"
        }
    }
} finally {
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
}
