[CmdletBinding()]
param(
    [switch]$Restart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$logsDir = Join-Path $repoRoot "logs"
$stdoutPath = Join-Path $logsDir "telegram-agent.out.log"
$stderrPath = Join-Path $logsDir "telegram-agent.err.log"
$matchPattern = "roughcut\.cli telegram-agent"

function Get-TelegramAgentProcesses {
    return @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -and $_.CommandLine -match $matchPattern
        }
    )
}

function Stop-TelegramAgentProcesses {
    foreach ($proc in (Get-TelegramAgentProcesses)) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        } catch {
        }
    }
}

if (-not (Test-Path $python)) {
    throw "Python executable not found: $python"
}

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

if ($Restart) {
    Stop-TelegramAgentProcesses
    Start-Sleep -Milliseconds 300
}

$existing = @(Get-TelegramAgentProcesses)
if ($existing.Count -ge 1) {
    if ($existing.Count -gt 1) {
        $existing | Select-Object -Skip 1 | ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            } catch {
            }
        }
    }
    Write-Host "Telegram agent is already running." -ForegroundColor Yellow
    exit 0
}

$process = Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "roughcut.cli", "telegram-agent") `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath

Write-Host "Telegram agent started (PID $($process.Id))." -ForegroundColor Green
