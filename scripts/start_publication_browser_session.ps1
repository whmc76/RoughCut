param(
    [string]$ChromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe",
    [string]$UserDataDir = "",
    [string]$ProfileDirectory = "",
    [int]$RemoteDebuggingPort = 9222,
    [string[]]$OpenUrl = @(),
    [switch]$NoDefaultUrls,
    [switch]$AllowDefaultUserDataDir,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-DefaultPublicationUserDataDir {
    $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR", "Process")
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR", "User")
    }
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR", "Machine")
    }
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        return $configured.Trim()
    }
    $chromeUserDataDir = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"
    if (Test-Path -LiteralPath $chromeUserDataDir) {
        return $chromeUserDataDir
    }
    return (Join-Path $repoRoot "data\runtime\publication-browser-profile-stable\chrome-user-data")
}

function Get-DefaultPublicationProfileDirectory {
    $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_PROFILE_DIRECTORY", "Process")
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_PROFILE_DIRECTORY", "User")
    }
    if ([string]::IsNullOrWhiteSpace($configured)) {
        $configured = [Environment]::GetEnvironmentVariable("ROUGHCUT_PUBLICATION_BROWSER_PROFILE_DIRECTORY", "Machine")
    }
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        return $configured.Trim()
    }
    return "Profile 2"
}

function Get-DefaultPublicationUrls {
    @(
        "https://creator.douyin.com/creator-micro/content/post/video",
        "https://creator.xiaohongshu.com/publish"
    )
}

function Normalize-ProfilePath {
    param(
        [string]$PathValue
    )
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    $expanded = [Environment]::ExpandEnvironmentVariables($PathValue.Trim())
    try {
        return [System.IO.Path]::GetFullPath($expanded).TrimEnd('\')
    } catch {
        return $expanded.TrimEnd('\')
    }
}

function Get-PublicationBrowserProfileId {
    param(
        [string]$Browser,
        [string]$ResolvedUserDataDir,
        [string]$ResolvedProfileDirectory
    )
    $normalizedBrowser = [string]$Browser
    if ([string]::IsNullOrWhiteSpace($normalizedBrowser)) {
        $normalizedBrowser = "chrome"
    }
    $normalizedBrowser = $normalizedBrowser.Trim().ToLowerInvariant().Replace(" ", "-").Replace("_", "-")
    $normalizedUserDataDir = (Normalize-ProfilePath $ResolvedUserDataDir).Replace("\", "/")
    $normalizedProfileDirectory = [string]$ResolvedProfileDirectory
    if ([string]::IsNullOrWhiteSpace($normalizedBrowser) -or [string]::IsNullOrWhiteSpace($normalizedUserDataDir) -or [string]::IsNullOrWhiteSpace($normalizedProfileDirectory)) {
        return ""
    }
    $payload = ($normalizedBrowser, $normalizedUserDataDir.ToLowerInvariant(), $normalizedProfileDirectory.Trim().ToLowerInvariant()) -join "`n"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        $hash = $sha1.ComputeHash($bytes)
    } finally {
        $sha1.Dispose()
    }
    $digest = ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant().Substring(0, 20)
    return "browser-profile:${normalizedBrowser}:$digest"
}

function Test-IsDefaultChromeUserDataDir {
    param(
        [string]$ResolvedUserDataDir
    )
    $defaultRoots = @(
        (Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"),
        (Join-Path $env:LOCALAPPDATA "Chromium\User Data"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\Edge\User Data")
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { Normalize-ProfilePath $_ }
    $normalized = Normalize-ProfilePath $ResolvedUserDataDir
    return $defaultRoots -contains $normalized
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
    $UserDataDir = Get-DefaultPublicationUserDataDir
}
if ([string]::IsNullOrWhiteSpace($ProfileDirectory)) {
    $ProfileDirectory = Get-DefaultPublicationProfileDirectory
}
if (-not (Test-Path -LiteralPath $ChromePath)) {
    throw "Chrome executable not found: $ChromePath"
}

$normalizedUserDataDir = Normalize-ProfilePath $UserDataDir
$normalizedProfileDirectory = $ProfileDirectory.Trim()
New-Item -ItemType Directory -Force -Path $normalizedUserDataDir | Out-Null
$profileId = Get-PublicationBrowserProfileId -Browser "chrome" -ResolvedUserDataDir $normalizedUserDataDir -ResolvedProfileDirectory $ProfileDirectory
if (-not $AllowDefaultUserDataDir -and (Test-IsDefaultChromeUserDataDir -ResolvedUserDataDir $normalizedUserDataDir)) {
    throw (
        "Unsafe publication browser launch blocked: default Chrome User Data root cannot be used for CDP publication " +
        "sessions on current Chrome versions. Use a dedicated non-default runtime profile root, or pass " +
        "-AllowDefaultUserDataDir only for explicit manual debugging."
    )
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
    -ResolvedUserDataDir $normalizedUserDataDir `
    -ResolvedProfileDirectory $normalizedProfileDirectory `
    -ResolvedRemoteDebuggingPort $RemoteDebuggingPort `
    -ResolvedUrls $resolvedUrls

if ($DryRun) {
    [pscustomobject]@{
        chrome_path = $ChromePath
        remote_debugging_port = $RemoteDebuggingPort
        user_data_dir = $normalizedUserDataDir
        profile_directory = $normalizedProfileDirectory
        profile_id = $profileId
        urls = $resolvedUrls
        argument_list = $arguments
        note = "Default launches persist on a stable dedicated publication profile root unless ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR / PROFILE_DIRECTORY overrides are set."
    } | ConvertTo-Json -Depth 6
    return
}

& $ChromePath @arguments | Out-Null
