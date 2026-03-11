param(
    [switch]$StopDocker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

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
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Host "$Name stopped (PID $($proc.ProcessId))." -ForegroundColor Green
        } catch {
            Write-Host "Failed to stop $Name (PID $($proc.ProcessId)): $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}

Stop-RoughCutProcess -Name "API" -Pattern "roughcut\.cli api --host 127\.0\.0\.1 --port"
Stop-RoughCutProcess -Name "Orchestrator" -Pattern "roughcut\.cli orchestrator --poll-interval"
Stop-RoughCutProcess -Name "Media worker" -Pattern "celery -A roughcut\.pipeline\.celery_app:celery_app worker --queues=media_queue"
Stop-RoughCutProcess -Name "LLM worker" -Pattern "celery -A roughcut\.pipeline\.celery_app:celery_app worker --queues=llm_queue"

if ($StopDocker) {
    Write-Host "Stopping docker compose services..." -ForegroundColor Cyan
    docker compose stop | Out-Host
}
