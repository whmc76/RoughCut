param(
    [string]$HeygemRepo = "E:/WorkSpace/heygem",
    [string]$IndexTtsRepo = "E:/WorkSpace/indextts2-service"
)

$ErrorActionPreference = "Stop"

function Start-ComposeRepo {
    param(
        [string]$RepoPath,
        [string]$Label
    )

    $composeFile = Join-Path $RepoPath "docker-compose.yml"
    if (-not (Test-Path $composeFile)) {
        throw "$Label compose file not found: $composeFile"
    }

    Write-Host "Starting $Label from $RepoPath" -ForegroundColor Cyan
    docker compose -f $composeFile up -d | Out-Host
}

foreach ($repo in @($HeygemRepo, $IndexTtsRepo)) {
    if (-not (Test-Path $repo)) {
        throw "Repository not found: $repo"
    }
}

Start-ComposeRepo -RepoPath $HeygemRepo -Label "HeyGem"
Start-ComposeRepo -RepoPath $IndexTtsRepo -Label "IndexTTS2"

Write-Host "HeyGem video API:     http://127.0.0.1:49202"
Write-Host "IndexTTS2 API:        http://127.0.0.1:49204"
