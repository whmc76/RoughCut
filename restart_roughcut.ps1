param(
    [int]$Port = 38471,
    [switch]$SkipDocker,
    [switch]$SkipMigrate,
    [switch]$CleanupLegacyDocker,
    [switch]$StopOnly,
    [switch]$StopDocker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Uv = Get-Command uv -ErrorAction SilentlyContinue
$SystemPython = Get-Command python -ErrorAction SilentlyContinue
$Npm = Get-Command npm -ErrorAction SilentlyContinue
$FrontendDir = Join-Path $RepoRoot "frontend"
$FrontendDist = Join-Path $FrontendDir "dist\index.html"

function Initialize-RoughCutEnvironment {
    if (Test-Path $Python) {
        return
    }

    Write-Host "Python virtual environment not found. Bootstrapping RoughCut..." -ForegroundColor Yellow

    if ($null -ne $Uv) {
        Write-Host "Using uv to create and sync .venv" -ForegroundColor Cyan
        & $Uv.Source sync --extra dev --extra local-asr
    } elseif ($null -ne $SystemPython) {
        Write-Host "uv not found. Falling back to python -m venv + pip install." -ForegroundColor Yellow
        & $SystemPython.Source -m venv .venv
        if (-not (Test-Path $Python)) {
            throw "Failed to create virtual environment: $Python"
        }
        & $Python -m pip install -e ".[dev,local-asr]"
    } else {
        throw "Neither uv nor python is available. Install uv, then run 'uv sync --extra dev --extra local-asr'."
    }

    if (-not (Test-Path $Python)) {
        throw "Virtual environment Python not found after bootstrap: $Python"
    }
}

function Ensure-RoughCutFrontend {
    if (-not (Test-Path $FrontendDir)) {
        return
    }

    if (Test-Path $FrontendDist) {
        return
    }

    if ($null -eq $Npm) {
        throw "npm is required to build the React frontend. Install Node.js 22+ and rerun."
    }

    Write-Host "Frontend build not found. Installing and building React app..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    try {
        if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
            if (Test-Path (Join-Path $FrontendDir "package-lock.json")) {
                & $Npm.Source ci
            } else {
                & $Npm.Source install
            }
        }
        & $Npm.Source run build
    } finally {
        Pop-Location
    }

    if (-not (Test-Path $FrontendDist)) {
        throw "Frontend build failed: $FrontendDist not found."
    }
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

function Get-ProcessMatches {
    param([string]$Pattern)

    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "python.exe" `
            -and $_.ExecutablePath `
            -and (Test-Path $Python) `
            -and [System.StringComparer]::OrdinalIgnoreCase.Equals($_.ExecutablePath, $Python) `
            -and $_.CommandLine `
            -and $_.CommandLine -match $Pattern
    } | Sort-Object ProcessId)
}

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

function Stop-RoughCutServices {
    param([switch]$StopDockerServices)

    Write-Host "Stopping existing RoughCut services..." -ForegroundColor Cyan
    Stop-RoughCutProcess -Name "API" -Pattern "roughcut\.cli api --host 127\.0\.0\.1 --port"
    Stop-RoughCutProcess -Name "Orchestrator" -Pattern "roughcut\.cli orchestrator --poll-interval"
    Stop-RoughCutProcess -Name "Media worker" -Pattern "celery -A roughcut\.pipeline\.celery_app:celery_app worker --queues=media_queue"
    Stop-RoughCutProcess -Name "LLM worker" -Pattern "celery -A roughcut\.pipeline\.celery_app:celery_app worker --queues=llm_queue"

    if ($StopDockerServices) {
        Write-Host "Stopping docker compose services..." -ForegroundColor Cyan
        docker compose stop | Out-Host
    }
}

function Start-RoughCutProcess {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [string]$MatchPattern,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    $matches = @(Get-ProcessMatches -Pattern $MatchPattern)
    if ($matches.Count -gt 1) {
        $matches | Select-Object -SkipLast 1 | ForEach-Object {
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
                Write-Host "Stopped duplicate $Name (PID $($_.ProcessId))." -ForegroundColor Yellow
            } catch {
            }
        }
        $matches = @(Get-ProcessMatches -Pattern $MatchPattern)
    }

    if ($matches.Count -eq 1) {
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

if ($StopOnly) {
    Stop-RoughCutServices -StopDockerServices:$StopDocker
    exit 0
}

Initialize-RoughCutEnvironment
Ensure-RoughCutFrontend

Stop-RoughCutServices

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
Write-Host "RoughCut restarted." -ForegroundColor Green
Write-Host "API URL: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Logs: .\logs\*.out.log / .\logs\*.err.log" -ForegroundColor DarkGray

if (Wait-ApiReady -TestPort $Port) {
    Start-Process "http://127.0.0.1:$Port/" | Out-Null
    Write-Host "GUI opened in your default browser." -ForegroundColor Green
} else {
    Write-Host "API did not become ready in time. Check logs if the GUI does not open." -ForegroundColor Yellow
}
