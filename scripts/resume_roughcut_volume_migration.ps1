param(
    [string]$MissingListPath = "F:/roughcut_outputs/jobs-missing.txt",
    [string]$TargetRoot = "F:/roughcut_outputs/jobs",
    [string]$VolumeName = "roughcut_minio_data"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $MissingListPath)) {
    throw "Missing list not found: $MissingListPath"
}

if (-not (Test-Path -LiteralPath $TargetRoot)) {
    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
}

$jobs = Get-Content -LiteralPath $MissingListPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
$total = $jobs.Count
$index = 0

foreach ($job in $jobs) {
    $index += 1
    $jobName = $job.Trim()
    if (-not $jobName) {
        continue
    }

    $targetPath = Join-Path $TargetRoot $jobName
    if (Test-Path -LiteralPath $targetPath) {
        Write-Host "[$index/$total] skip existing $jobName"
        continue
    }

    Write-Host "[$index/$total] copying $jobName"
    docker run --rm -v "${VolumeName}:/from" -v "${TargetRoot}:/to" alpine sh -lc "cp -a /from/roughcut/jobs/$jobName /to/$jobName"
}
