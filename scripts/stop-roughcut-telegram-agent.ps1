[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$matchPattern = "roughcut\.cli telegram-agent"
$processes = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match $matchPattern
    }
)

if ($processes.Count -eq 0) {
    Write-Host "Telegram agent is not running." -ForegroundColor Yellow
    exit 0
}

foreach ($proc in $processes) {
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        Write-Host "Telegram agent stopped (PID $($proc.ProcessId))." -ForegroundColor Green
    } catch {
        $message = $_.Exception.Message
        if ($message -match "Cannot find a process with the process identifier") {
            Write-Host "Telegram agent already exited (PID $($proc.ProcessId))." -ForegroundColor Yellow
            continue
        }
        Write-Host "Failed to stop Telegram agent (PID $($proc.ProcessId)): $message" -ForegroundColor Red
        exit 1
    }
}
