<#
.SYNOPSIS
Rewrite a local mirror with git-filter-repo to remove private files and
replace sensitive literals before an open-source release.

.DESCRIPTION
The script clones a mirror of the source repository, runs
`python -m git_filter_repo`, then validates the rewritten result by scanning the
sanitized checkout for replacement-source literals and checking that literal
paths no longer appear in history.
#>

param(
  [Parameter(Mandatory = $true)]
  [string]$SourceRepo,

  [Parameter(Mandatory = $true)]
  [string]$WorkDir,

  [Parameter(Mandatory = $true)]
  [string]$PathsFile,

  [Parameter(Mandatory = $true)]
  [string]$ReplaceTextFile,

  [switch]$SkipValidation,

  [switch]$AllowDirtySourceRepo
)

$ErrorActionPreference = "Stop"

function Resolve-AbsolutePath {
  param([string]$PathValue)

  $resolved = Resolve-Path -LiteralPath $PathValue
  return $resolved.ProviderPath
}

function Remove-DirectoryIfPresent {
  param([string]$TargetPath)

  if (Test-Path -LiteralPath $TargetPath) {
    Remove-Item -LiteralPath $TargetPath -Recurse -Force
  }
}

function Invoke-Git {
  param(
    [string[]]$Arguments,
    [string]$WorkingDirectory
  )

  $quoted = $Arguments | ForEach-Object {
    if ($_ -match "\s") { '"{0}"' -f $_ } else { $_ }
  }
  Write-Host ("git " + ($quoted -join " "))
  & git @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "git command failed with exit code $LASTEXITCODE"
  }
}

function Test-GitWorkTree {
  param([string]$RepositoryPath)

  Push-Location $RepositoryPath
  try {
    & git "rev-parse" "--is-inside-work-tree"
    if ($LASTEXITCODE -ne 0) {
      return $false
    }
    return $true
  } finally {
    Pop-Location
  }
}

function Assert-CleanSourceRepoIfWorkTree {
  param(
    [string]$RepositoryPath,
    [bool]$AllowDirty
  )

  if (-not (Test-GitWorkTree -RepositoryPath $RepositoryPath)) {
    return
  }

  Push-Location $RepositoryPath
  try {
    $statusLines = & git "status" "--short"
    if ($LASTEXITCODE -ne 0) {
      throw "Unable to inspect source repo status."
    }
    if ($statusLines -and -not $AllowDirty) {
      throw @"
Source repo has uncommitted changes. The history rewrite only operates on committed history,
so running it now would ignore the latest worktree-only sanitization changes.

Commit or stash the final open-source cleanup first, then rerun this script.
If you intentionally want to rewrite committed history while ignoring current worktree changes,
rerun with -AllowDirtySourceRepo.
"@
    }
  } finally {
    Pop-Location
  }
}

function Invoke-Python {
  param(
    [string[]]$Arguments,
    [string]$WorkingDirectory
  )

  $quoted = $Arguments | ForEach-Object {
    if ($_ -match "\s") { '"{0}"' -f $_ } else { $_ }
  }
  Write-Host ("python " + ($quoted -join " "))
  Push-Location $WorkingDirectory
  try {
    & python @Arguments
    if ($LASTEXITCODE -ne 0) {
      throw "python command failed with exit code $LASTEXITCODE"
    }
  } finally {
    Pop-Location
  }
}

function Get-ValidationPatternsFromReplaceFile {
  param([string]$FilePath)

  $patterns = @()
  foreach ($line in Get-Content -LiteralPath $FilePath -Encoding UTF8) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("==>")) {
      continue
    }
    $left = $trimmed.Split("==>", 2)[0]
    if ($left.StartsWith("literal:")) {
      $patterns += $left.Substring("literal:".Length)
    }
  }
  return $patterns
}

function Get-LiteralPathsFromPathsFile {
  param([string]$FilePath)

  $paths = @()
  foreach ($line in Get-Content -LiteralPath $FilePath -Encoding UTF8) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) {
      continue
    }
    if ($trimmed.StartsWith("literal:")) {
      $paths += $trimmed.Substring("literal:".Length)
    }
  }
  return $paths
}

function Invoke-ReadinessAuditIfPresent {
  param([string]$CheckoutDirectory)

  $auditScript = Join-Path $CheckoutDirectory "scripts\check_open_source_readiness.py"
  if (-not (Test-Path -LiteralPath $auditScript -PathType Leaf)) {
    return
  }

  Invoke-Python -Arguments @("scripts/check_open_source_readiness.py", "--scope", "both") -WorkingDirectory $CheckoutDirectory
}

$sourceRepoPath = Resolve-AbsolutePath $SourceRepo
$pathsFilePath = Resolve-AbsolutePath $PathsFile
$replaceTextFilePath = Resolve-AbsolutePath $ReplaceTextFile

if (-not (Test-Path -LiteralPath $sourceRepoPath -PathType Container)) {
  throw "Source repo does not exist: $sourceRepoPath"
}
if (-not (Test-Path -LiteralPath $pathsFilePath -PathType Leaf)) {
  throw "Paths file does not exist: $pathsFilePath"
}
if (-not (Test-Path -LiteralPath $replaceTextFilePath -PathType Leaf)) {
  throw "Replace-text file does not exist: $replaceTextFilePath"
}

Assert-CleanSourceRepoIfWorkTree -RepositoryPath $sourceRepoPath -AllowDirty:$AllowDirtySourceRepo

$workDirPath = [System.IO.Path]::GetFullPath($WorkDir)
$mirrorDir = Join-Path $workDirPath "mirror.git"
$checkoutDir = Join-Path $workDirPath "checkout"

New-Item -ItemType Directory -Path $workDirPath -Force | Out-Null
Remove-DirectoryIfPresent $mirrorDir
Remove-DirectoryIfPresent $checkoutDir

Invoke-Git -Arguments @("clone", "--mirror", $sourceRepoPath, $mirrorDir) -WorkingDirectory $workDirPath

Push-Location $mirrorDir
try {
  Invoke-Python -Arguments @(
    "-m",
    "git_filter_repo",
    "--sensitive-data-removal",
    "--no-fetch",
    "--invert-paths",
    "--paths-from-file",
    $pathsFilePath,
    "--replace-text",
    $replaceTextFilePath,
    "--force"
  ) -WorkingDirectory $mirrorDir
} finally {
  Pop-Location
}

if (-not $SkipValidation) {
  Invoke-Git -Arguments @("clone", $mirrorDir, $checkoutDir) -WorkingDirectory $workDirPath
  Invoke-ReadinessAuditIfPresent -CheckoutDirectory $checkoutDir

  $validationPatterns = Get-ValidationPatternsFromReplaceFile -FilePath $replaceTextFilePath
  foreach ($pattern in $validationPatterns) {
    $matches = & git -C $checkoutDir grep -n -I -F -- $pattern HEAD
    if ($LASTEXITCODE -eq 0) {
      throw "Validation failed: found residual pattern '$pattern' in sanitized checkout."
    }
  }

  $literalPaths = Get-LiteralPathsFromPathsFile -FilePath $pathsFilePath
  foreach ($literalPath in $literalPaths) {
    $historyMatches = & git "--git-dir=$mirrorDir" "log" "--all" "--format=%H" "--" $literalPath
    if ($LASTEXITCODE -ne 0) {
      throw "git log validation failed for path '$literalPath'."
    }
    if ($historyMatches) {
      throw "Validation failed: path '$literalPath' still exists in sanitized history."
    }
  }
}

Write-Host "Sanitized mirror:"
Write-Host "  $mirrorDir"
if (-not $SkipValidation) {
  Write-Host "Validation checkout:"
  Write-Host "  $checkoutDir"
}
