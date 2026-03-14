param(
    [string]$ComposeDir = "deploy/heygem-shared"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $repoRoot $ComposeDir
$composeFile = Join-Path $targetDir "docker-compose.yml"
$envFile = Join-Path $targetDir ".env"
$exampleEnvFile = Join-Path $targetDir ".env.example"

if (-not (Test-Path $composeFile)) {
    throw "Compose file not found: $composeFile"
}

if (-not (Test-Path $envFile)) {
    Copy-Item $exampleEnvFile $envFile
}

$envMap = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match "^\s*#") { return }
    if ($_ -notmatch "=") { return }
    $parts = $_ -split "=", 2
    $envMap[$parts[0].Trim()] = $parts[1].Trim()
}

$sharedRoot = $envMap["HEYGEM_SHARED_HOST_DIR"]
$voiceRoot = $envMap["HEYGEM_VOICE_HOST_DIR"]

if (-not $sharedRoot) {
    throw "HEYGEM_SHARED_HOST_DIR missing in $envFile"
}
if (-not $voiceRoot) {
    throw "HEYGEM_VOICE_HOST_DIR missing in $envFile"
}

New-Item -ItemType Directory -Force -Path $sharedRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $sharedRoot "inputs/audio") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $sharedRoot "inputs/video") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $sharedRoot "temp") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $sharedRoot "result") | Out-Null
New-Item -ItemType Directory -Force -Path $voiceRoot | Out-Null

docker compose --env-file $envFile -f $composeFile up -d

Write-Host "HeyGem video API:     http://127.0.0.1:$($envMap['HEYGEM_API_PORT'])"
Write-Host "Fish Speech train API:http://127.0.0.1:$($envMap['HEYGEM_TRAINING_API_PORT'])"
