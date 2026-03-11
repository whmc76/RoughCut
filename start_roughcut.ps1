param(
    [int]$Port = 38471,
    [switch]$SkipDocker,
    [switch]$SkipMigrate,
    [switch]$CleanupLegacyDocker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
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

function Test-ProcessCommandLine {
    param([string]$Pattern)

    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
    if (-not $procs) {
        return $false
    }

    return $null -ne ($procs | Where-Object {
        $_.CommandLine -and $_.CommandLine -match $Pattern
    } | Select-Object -First 1)
}

function Start-RoughCutProcess {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [string]$MatchPattern,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    if (Test-ProcessCommandLine -Pattern $MatchPattern) {
        Write-Host "$Name is already running. Skipping." -ForegroundColor Yellow
        return
    }

    Start-Process `
        -FilePath $Python `
        -ArgumentList $Arguments `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath | Out-Null

    Write-Host "$Name started." -ForegroundColor Green
}

function Wait-ApiReady {
    param(
        [int]$TestPort,
        [int]$TimeoutSec = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $url = "http://127.0.0.1:$TestPort/health"
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 2
            if ($response.status -eq "ok") {
                return $true
            }
        } catch {
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Show-LauncherStatus {
    param([int]$ActivePort)

    Write-Host ""
    Write-Host "Launcher status" -ForegroundColor Cyan
    Write-Host "API:    http://127.0.0.1:$ActivePort/" -ForegroundColor Green
    Write-Host "Logs:   .\logs\*.out.log / .\logs\*.err.log" -ForegroundColor DarkGray
    Write-Host "Stop:   type 'stop' in this console or run stop_roughcut.bat" -ForegroundColor DarkGray
}

if (-not $SkipDocker) {
    Write-Host "Checking Docker services..." -ForegroundColor Cyan
    $dockerNames = @("roughcut-postgres-1", "roughcut-redis-1", "roughcut-minio-1")
    $legacyDockerNames = @("fastcut-postgres-1", "fastcut-redis-1", "fastcut-minio-1")
    $running = @()
    try {
        $running = docker ps -a --format "{{.Names}}"
    } catch {
        throw "Failed to run docker. Make sure Docker Desktop is running."
    }

    $legacy = @($legacyDockerNames | Where-Object { $_ -in $running })
    if ($legacy.Count -gt 0) {
        if (-not $CleanupLegacyDocker) {
            throw "Legacy FastCut containers detected: $($legacy -join ', '). Run 'docker rm -f $($legacy -join ' ')' or rerun with -CleanupLegacyDocker."
        }
        Write-Host "Removing legacy FastCut containers..." -ForegroundColor Yellow
        docker rm -f $legacy | Out-Host
        $running = docker ps -a --format "{{.Names}}"
    }

    $missing = @($dockerNames | Where-Object { $_ -notin $running })
    if ($missing.Count -gt 0) {
        Write-Host "Starting docker compose services..." -ForegroundColor Yellow
        docker compose up -d | Out-Host
    } else {
        Write-Host "Docker services are ready." -ForegroundColor Green
    }
}

if (-not $SkipMigrate) {
    Write-Host "Running database migrations..." -ForegroundColor Cyan
    & $Python -m roughcut.cli migrate
}

if (Test-PortListening -TestPort $Port) {
    if ($Port -eq 38471) {
        Write-Host "Port 38471 is busy. Switching to 38472." -ForegroundColor Yellow
        $Port = 38472
    } else {
        throw "Port $Port is already in use. Choose a different port."
    }
}

New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "logs") | Out-Null

Write-Host "Starting RoughCut services..." -ForegroundColor Cyan
Start-RoughCutProcess `
    -Name "API" `
    -Arguments @("-m", "roughcut.cli", "api", "--host", "127.0.0.1", "--port", "$Port") `
    -MatchPattern ([regex]::Escape("roughcut.cli api --host 127.0.0.1 --port $Port")) `
    -StdoutPath (Join-Path $RepoRoot "logs\api.out.log") `
    -StderrPath (Join-Path $RepoRoot "logs\api.err.log")
Start-RoughCutProcess `
    -Name "Orchestrator" `
    -Arguments @("-m", "roughcut.cli", "orchestrator", "--poll-interval", "2") `
    -MatchPattern ([regex]::Escape("roughcut.cli orchestrator --poll-interval 2")) `
    -StdoutPath (Join-Path $RepoRoot "logs\orchestrator.out.log") `
    -StderrPath (Join-Path $RepoRoot "logs\orchestrator.err.log")
Start-RoughCutProcess `
    -Name "Media worker" `
    -Arguments @("-m", "celery", "-A", "roughcut.pipeline.celery_app:celery_app", "worker", "--queues=media_queue", "--pool=solo", "--concurrency=1", "--loglevel=info") `
    -MatchPattern ([regex]::Escape("celery -A roughcut.pipeline.celery_app:celery_app worker --queues=media_queue --pool=solo --concurrency=1 --loglevel=info")) `
    -StdoutPath (Join-Path $RepoRoot "logs\media-worker.out.log") `
    -StderrPath (Join-Path $RepoRoot "logs\media-worker.err.log")
Start-RoughCutProcess `
    -Name "LLM worker" `
    -Arguments @("-m", "celery", "-A", "roughcut.pipeline.celery_app:celery_app", "worker", "--queues=llm_queue", "--pool=solo", "--concurrency=1", "--loglevel=info") `
    -MatchPattern ([regex]::Escape("celery -A roughcut.pipeline.celery_app:celery_app worker --queues=llm_queue --pool=solo --concurrency=1 --loglevel=info")) `
    -StdoutPath (Join-Path $RepoRoot "logs\llm-worker.out.log") `
    -StderrPath (Join-Path $RepoRoot "logs\llm-worker.err.log")

Write-Host ""
Write-Host "RoughCut started." -ForegroundColor Green
Write-Host "API URL: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Logs: .\logs\*.out.log / .\logs\*.err.log" -ForegroundColor DarkGray

if (Wait-ApiReady -TestPort $Port) {
    Start-Process "http://127.0.0.1:$Port/" | Out-Null
    Write-Host "GUI opened in your default browser." -ForegroundColor Green
} else {
    Write-Host "API did not become ready in time. Check logs if the GUI does not open." -ForegroundColor Yellow
}

Show-LauncherStatus -ActivePort $Port
Write-Host ""
Write-Host "Commands: status | open | stop | exit" -ForegroundColor Cyan

while ($true) {
    $command = (Read-Host "roughcut").Trim().ToLowerInvariant()
    switch ($command) {
        "status" {
            Show-LauncherStatus -ActivePort $Port
        }
        "open" {
            Start-Process "http://127.0.0.1:$Port/" | Out-Null
            Write-Host "GUI opened." -ForegroundColor Green
        }
        "stop" {
            & (Join-Path $RepoRoot "stop_roughcut.ps1")
            break
        }
        "exit" {
            Write-Host "Launcher closed. Services keep running in the background." -ForegroundColor Yellow
            break
        }
        "" {
        }
        default {
            Write-Host "Unknown command. Use: status | open | stop | exit" -ForegroundColor Yellow
        }
    }
}
