Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [int]$Port = 8000,
    [switch]$SkipDocker,
    [switch]$SkipMigrate
)

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "未找到虚拟环境 Python: $Python"
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

function Start-RoughCutWindow {
    param(
        [string]$Title,
        [string]$Command
    )

    $escapedRoot = $RepoRoot.Replace("'", "''")
    $escapedTitle = $Title.Replace("'", "''")
    $script = @"
`$Host.UI.RawUI.WindowTitle = '$escapedTitle'
Set-Location '$escapedRoot'
`$env:PYTHONPATH = 'src'
$Command
"@
    Start-Process pwsh -ArgumentList "-NoExit", "-Command", $script | Out-Null
}

if (-not $SkipDocker) {
    Write-Host "检查 Docker 基础服务..." -ForegroundColor Cyan
    $dockerNames = @("roughcut-postgres-1", "roughcut-redis-1", "roughcut-minio-1")
    $running = @()
    try {
        $running = docker ps --format "{{.Names}}"
    } catch {
        throw "无法执行 docker，请确认 Docker Desktop 已启动。"
    }

    $missing = $dockerNames | Where-Object { $_ -notin $running }
    if ($missing.Count -gt 0) {
        Write-Host "启动 docker-compose 基础服务..." -ForegroundColor Yellow
        docker compose up -d | Out-Host
    } else {
        Write-Host "Docker 基础服务已就绪。" -ForegroundColor Green
    }
}

if (-not $SkipMigrate) {
    Write-Host "执行数据库迁移..." -ForegroundColor Cyan
    & $Python -m roughcut.cli migrate
}

if (Test-PortListening -TestPort $Port) {
    if ($Port -eq 8000) {
        Write-Host "端口 8000 已被占用，自动切换到 8010。" -ForegroundColor Yellow
        $Port = 8010
    } else {
        throw "端口 $Port 已被占用，请更换端口后重试。"
    }
}

Write-Host "启动 RoughCut 服务..." -ForegroundColor Cyan
Start-RoughCutWindow -Title "RoughCut API" -Command "& '$Python' -m roughcut.cli api --host 127.0.0.1 --port $Port"
Start-RoughCutWindow -Title "RoughCut Orchestrator" -Command "& '$Python' -m roughcut.cli orchestrator --poll-interval 2"
Start-RoughCutWindow -Title "RoughCut Media Worker" -Command "& '$Python' -m celery -A roughcut.pipeline.celery_app:celery_app worker --queues=media_queue --pool=solo --concurrency=1 --loglevel=info"
Start-RoughCutWindow -Title "RoughCut LLM Worker" -Command "& '$Python' -m celery -A roughcut.pipeline.celery_app:celery_app worker --queues=llm_queue --pool=solo --concurrency=1 --loglevel=info"

Write-Host ""
Write-Host "RoughCut 已启动。" -ForegroundColor Green
Write-Host "API 地址: http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "说明: 该脚本仅在你手动执行时启动，不会后台自启动。" -ForegroundColor DarkGray
