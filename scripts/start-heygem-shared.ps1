param(
    [string]$HeygemRepo = "E:/WorkSpace/heygem",
    [string]$IndexTtsRepo = "E:/WorkSpace/indextts2-service",
    [switch]$IncludeIndexTts
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PortsEnvFile = Join-Path $RepoRoot "roughcut.ports.env"

function Get-PortsEnvValue {
    param([string]$Key)

    if (-not (Test-Path $PortsEnvFile)) {
        return $null
    }
    $escapedKey = [regex]::Escape($Key)
    foreach ($line in Get-Content $PortsEnvFile) {
        if ($line -match "^\s*$escapedKey\s*=\s*([^#]*?)(\s+#.*)?$") {
            $raw = $Matches[1].Trim()
            if (($raw.StartsWith('"') -and $raw.EndsWith('"')) -or ($raw.StartsWith("'") -and $raw.EndsWith("'"))) {
                return $raw.Substring(1, $raw.Length - 2)
            }
            return $raw
        }
    }
    return $null
}

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

foreach ($repo in @($HeygemRepo)) {
    if (-not (Test-Path $repo)) {
        throw "Repository not found: $repo"
    }
}
if ($IncludeIndexTts -and -not (Test-Path $IndexTtsRepo)) {
    throw "Repository not found: $IndexTtsRepo"
}

Start-ComposeRepo -RepoPath $HeygemRepo -Label "HeyGem"
if ($IncludeIndexTts) {
    Start-ComposeRepo -RepoPath $IndexTtsRepo -Label "IndexTTS2"
}

$heygemApiPort = Get-PortsEnvValue -Key "HEYGEM_API_PORT"
$indexTtsApiPort = Get-PortsEnvValue -Key "INDEXTTS2_API_PORT"
if ([string]::IsNullOrWhiteSpace($heygemApiPort)) { $heygemApiPort = "49202" }
if ([string]::IsNullOrWhiteSpace($indexTtsApiPort)) { $indexTtsApiPort = "49204" }

Write-Host "HeyGem video API:     http://127.0.0.1:$heygemApiPort"
if ($IncludeIndexTts) {
    Write-Host "IndexTTS2 API:        http://127.0.0.1:$indexTtsApiPort"
} else {
    Write-Host "IndexTTS2 skipped. Pass -IncludeIndexTts only for local IndexTTS2 workflows."
}
