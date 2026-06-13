param(
    [switch]$DryRun,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$targets = @(
    ".external-services",
    "tmp",
    "frontend\.codex-logs",
    "debug_artifacts",
    "debug_out"
)

foreach ($relative in $targets) {
    $candidate = Join-Path $repoRoot $relative
    if (-not (Test-Path -LiteralPath $candidate)) {
        continue
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if (-not $resolved.StartsWith($repoRoot)) {
        throw "Refusing to remove path outside workspace: $resolved"
    }
    if ($DryRun) {
        if (-not $Quiet) {
            Write-Output "[would-remove] $resolved"
        }
        continue
    }
    try {
        Remove-Item -LiteralPath $resolved -Recurse -Force
        if (-not $Quiet) {
            Write-Output "[removed] $resolved"
        }
    } catch {
        Write-Warning "Failed to remove ${resolved}: $($_.Exception.Message)"
    }
}
