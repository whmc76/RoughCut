param(
    [string]$ChromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe",
    [string]$UserDataDir,
    [string]$ProfileDirectory,
    [int]$RemoteDebuggingPort = 9222,
    [string[]]$OpenUrl = @(),
    [switch]$NoDefaultUrls,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-DefaultPublicationUrls {
    @(
        "https://creator.douyin.com/creator-micro/content/post/video",
        "https://creator.xiaohongshu.com/publish"
    )
}

function Get-LaunchArguments {
    param(
        [string]$ResolvedUserDataDir,
        [string]$ResolvedProfileDirectory,
        [int]$ResolvedRemoteDebuggingPort,
        [string[]]$ResolvedUrls
    )

    $arguments = @(
        "--remote-debugging-port=$ResolvedRemoteDebuggingPort",
        "--user-data-dir=$ResolvedUserDataDir",
        "--profile-directory=$ResolvedProfileDirectory",
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-allow-origins=*"
    )
    foreach ($url in $ResolvedUrls) {
        if ([string]::IsNullOrWhiteSpace($url)) {
            continue
        }
        $arguments += $url.Trim()
    }
    return ,$arguments
}

if ([string]::IsNullOrWhiteSpace($UserDataDir)) {
    throw "Missing -UserDataDir. Do not launch publication Chrome without an explicit profile root."
}
if ([string]::IsNullOrWhiteSpace($ProfileDirectory)) {
    throw "Missing -ProfileDirectory. Do not launch publication Chrome without an explicit profile directory."
}
if (-not (Test-Path -LiteralPath $ChromePath)) {
    throw "Chrome executable not found: $ChromePath"
}

$resolvedUrls = @()
if (-not $NoDefaultUrls) {
    $resolvedUrls += Get-DefaultPublicationUrls
}
foreach ($url in $OpenUrl) {
    if ([string]::IsNullOrWhiteSpace($url)) {
        continue
    }
    $resolvedUrls += $url.Trim()
}
$resolvedUrls = @($resolvedUrls | Select-Object -Unique)

$arguments = Get-LaunchArguments `
    -ResolvedUserDataDir $UserDataDir.Trim() `
    -ResolvedProfileDirectory $ProfileDirectory.Trim() `
    -ResolvedRemoteDebuggingPort $RemoteDebuggingPort `
    -ResolvedUrls $resolvedUrls

if ($DryRun) {
    [pscustomobject]@{
        chrome_path = $ChromePath
        remote_debugging_port = $RemoteDebuggingPort
        user_data_dir = $UserDataDir.Trim()
        profile_directory = $ProfileDirectory.Trim()
        urls = $resolvedUrls
        argument_list = $arguments
        note = "Use native argument splatting so values like 'User Data' and 'Profile 2' stay single arguments instead of turning into bogus tabs."
    } | ConvertTo-Json -Depth 6
    return
}

& $ChromePath @arguments | Out-Null
