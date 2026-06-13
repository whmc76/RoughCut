param(
    [string]$ChromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe",
    [string]$CreatorProfileId = "",
    [string]$Platform = "",
    [string]$ProfilesJson = "",
    [string]$UserDataDir = "",
    [string]$ProfileDirectory = "",
    [string]$BridgeExtensionPath = "",
    [string[]]$OpenUrl = @(),
    [switch]$DisableBridgeExtension,
    [switch]$NoDefaultUrls,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$cleanupWorkspaceRuntime = [Environment]::GetEnvironmentVariable("ROUGHCUT_SKIP_WORKSPACE_RUNTIME_CLEANUP", "Process")
if ([string]::IsNullOrWhiteSpace($cleanupWorkspaceRuntime)) {
    $cleanupWorkspaceRuntime = [Environment]::GetEnvironmentVariable("ROUGHCUT_SKIP_WORKSPACE_RUNTIME_CLEANUP", "User")
}
if ([string]::IsNullOrWhiteSpace($cleanupWorkspaceRuntime)) {
    $cleanupWorkspaceRuntime = [Environment]::GetEnvironmentVariable("ROUGHCUT_SKIP_WORKSPACE_RUNTIME_CLEANUP", "Machine")
}
$skipWorkspaceRuntimeCleanup = @("1", "true", "yes") -contains ([string]$cleanupWorkspaceRuntime).Trim().ToLowerInvariant()
if (-not $skipWorkspaceRuntimeCleanup) {
    $cleanupScript = Join-Path $repoRoot "scripts\cleanup_workspace_runtime.ps1"
    if (Test-Path -LiteralPath $cleanupScript) {
        & $cleanupScript -Quiet
    }
}

if ([string]::IsNullOrWhiteSpace($ProfilesJson)) {
    $ProfilesJson = Join-Path $repoRoot "data\avatar_materials\profiles.json"
}

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

function Resolve-CreatorPublicationBrowserBinding {
    param(
        [string]$ProfilesJsonPath,
        [string]$ResolvedCreatorProfileId,
        [string]$ResolvedPlatform
    )
    if ([string]::IsNullOrWhiteSpace($ResolvedCreatorProfileId) -or -not (Test-Path -LiteralPath $ProfilesJsonPath)) {
        return $null
    }
    $payload = Get-Content -LiteralPath $ProfilesJsonPath -Raw | ConvertFrom-Json
    $profiles = @($payload)
    $profile = $profiles | Where-Object { [string]($_.id) -eq $ResolvedCreatorProfileId } | Select-Object -First 1
    if (-not $profile) {
        throw "Creator profile not found: $ResolvedCreatorProfileId"
    }
    $credentials = @($profile.creator_profile.publishing.platform_credentials)
    if (-not $credentials.Count) {
        return $null
    }
    $normalizedPlatform = [string]$ResolvedPlatform
    if ([string]::IsNullOrWhiteSpace($normalizedPlatform)) {
        $normalizedPlatform = ""
    }
    $normalizedPlatform = $normalizedPlatform.Trim().ToLowerInvariant()
    $credential = $null
    if ($normalizedPlatform) {
        $credential = $credentials | Where-Object { [string]($_.platform).Trim().ToLowerInvariant() -eq $normalizedPlatform } | Select-Object -First 1
    }
    if (-not $credential) {
        $credential = $credentials | Where-Object { $_.enabled -eq $true -and [string]($_.status).Trim().ToLowerInvariant() -eq "logged_in" } | Select-Object -First 1
    }
    if (-not $credential) {
        return $null
    }
    return $credential.browser_binding
}

function Get-DefaultPublicationUrls {
    @()
}

function Get-DefaultPublicationBridgeExtensionPath {
    return (Join-Path $repoRoot "browser\publication-bridge-extension")
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

function Get-LaunchArguments {
    param(
        [string]$ResolvedUserDataDir,
        [string]$ResolvedProfileDirectory,
        [string]$ResolvedBridgeExtensionPath,
        [bool]$DisableResolvedBridgeExtension,
        [string[]]$ResolvedUrls
    )

    $arguments = @(
        "--user-data-dir=$ResolvedUserDataDir",
        "--profile-directory=$ResolvedProfileDirectory",
        "--no-first-run",
        "--no-default-browser-check"
    )
    if (-not $DisableResolvedBridgeExtension -and -not [string]::IsNullOrWhiteSpace($ResolvedBridgeExtensionPath)) {
        $arguments += "--load-extension=$ResolvedBridgeExtensionPath"
    }
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
if ([string]::IsNullOrWhiteSpace($BridgeExtensionPath)) {
    $BridgeExtensionPath = Get-DefaultPublicationBridgeExtensionPath
}
if (-not [string]::IsNullOrWhiteSpace($CreatorProfileId)) {
    $browserBinding = Resolve-CreatorPublicationBrowserBinding -ProfilesJsonPath $ProfilesJson -ResolvedCreatorProfileId $CreatorProfileId.Trim() -ResolvedPlatform $Platform
    if ($browserBinding) {
        if ([string]::IsNullOrWhiteSpace($UserDataDir) -or $UserDataDir -eq (Get-DefaultPublicationUserDataDir)) {
            $resolvedBindingUserDataDir = [string]$browserBinding.user_data_dir
            if (-not [string]::IsNullOrWhiteSpace($resolvedBindingUserDataDir)) {
                $UserDataDir = $resolvedBindingUserDataDir
            }
        }
        if ([string]::IsNullOrWhiteSpace($ProfileDirectory) -or $ProfileDirectory -eq (Get-DefaultPublicationProfileDirectory)) {
            $resolvedBindingProfileDirectory = [string]$browserBinding.profile_directory
            if (-not [string]::IsNullOrWhiteSpace($resolvedBindingProfileDirectory)) {
                $ProfileDirectory = $resolvedBindingProfileDirectory
            }
        }
    }
}
if (-not (Test-Path -LiteralPath $ChromePath)) {
    throw "Chrome executable not found: $ChromePath"
}

$normalizedUserDataDir = Normalize-ProfilePath $UserDataDir
$normalizedProfileDirectory = $ProfileDirectory.Trim()
$normalizedBridgeExtensionPath = Normalize-ProfilePath $BridgeExtensionPath
New-Item -ItemType Directory -Force -Path $normalizedUserDataDir | Out-Null
$profileId = Get-PublicationBrowserProfileId -Browser "chrome" -ResolvedUserDataDir $normalizedUserDataDir -ResolvedProfileDirectory $ProfileDirectory

if (-not $DisableBridgeExtension) {
    if ([string]::IsNullOrWhiteSpace($normalizedBridgeExtensionPath)) {
        throw "Publication bridge extension path is empty."
    }
    if (-not (Test-Path -LiteralPath $normalizedBridgeExtensionPath)) {
        throw "Publication bridge extension directory not found: $normalizedBridgeExtensionPath"
    }
    $bridgeManifestPath = Join-Path $normalizedBridgeExtensionPath "manifest.json"
    if (-not (Test-Path -LiteralPath $bridgeManifestPath)) {
        throw "Publication bridge extension manifest not found: $bridgeManifestPath"
    }
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
    -ResolvedBridgeExtensionPath $normalizedBridgeExtensionPath `
    -DisableResolvedBridgeExtension $DisableBridgeExtension.IsPresent `
    -ResolvedUrls $resolvedUrls

if ($DryRun) {
    [pscustomobject]@{
        chrome_path = $ChromePath
        user_data_dir = $normalizedUserDataDir
        profile_directory = $normalizedProfileDirectory
        profile_id = $profileId
        bridge_extension_path = $(if ($DisableBridgeExtension) { "" } else { $normalizedBridgeExtensionPath })
        bridge_extension_enabled = (-not $DisableBridgeExtension.IsPresent)
        urls = $resolvedUrls
        argument_list = $arguments
        note = "Bridge-mode publication launches reuse the real Chrome profile bound by RoughCut, auto-load the publication bridge extension, and open explicit start pages in new tabs."
    } | ConvertTo-Json -Depth 6
    return
}

& $ChromePath @arguments | Out-Null
