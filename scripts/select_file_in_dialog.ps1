param(
  [Parameter(Mandatory = $true)]
  [string]$FilePath,

  [int]$TimeoutSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class NativeWindowTools {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

  [DllImport("user32.dll")]
  public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

  [DllImport("user32.dll")]
  public static extern bool IsWindowVisible(IntPtr hWnd);

  [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
  public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

  [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
  public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

  [DllImport("user32.dll")]
  public static extern bool SetForegroundWindow(IntPtr hWnd);

  [DllImport("user32.dll")]
  public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

if (-not (Test-Path -LiteralPath $FilePath)) {
  throw "File does not exist: $FilePath"
}

function Get-DialogWindow {
  $candidates = New-Object System.Collections.Generic.List[object]
  $callback = [NativeWindowTools+EnumWindowsProc]{
    param($hWnd, $lParam)

    if (-not [NativeWindowTools]::IsWindowVisible($hWnd)) {
      return $true
    }

    $titleBuilder = New-Object System.Text.StringBuilder 512
    [void][NativeWindowTools]::GetWindowText($hWnd, $titleBuilder, $titleBuilder.Capacity)
    $title = $titleBuilder.ToString().Trim()
    if ([string]::IsNullOrWhiteSpace($title)) {
      return $true
    }

    $classBuilder = New-Object System.Text.StringBuilder 128
    [void][NativeWindowTools]::GetClassName($hWnd, $classBuilder, $classBuilder.Capacity)
    $className = $classBuilder.ToString().Trim()

    if ($className -ne '#32770') {
      return $true
    }

    if ($title -match '^(打开|Open|Choose File|Choose file|文件上传|选择文件|选择要上传的文件)') {
      $candidates.Add([pscustomobject]@{
        Handle = $hWnd
        Title = $title
        ClassName = $className
      })
    }
    return $true
  }

  [void][NativeWindowTools]::EnumWindows($callback, [IntPtr]::Zero)
  return $candidates | Select-Object -First 1
}

$deadline = (Get-Date).AddSeconds([Math]::Max(3, $TimeoutSeconds))
$dialog = $null
while ((Get-Date) -lt $deadline) {
  $dialog = Get-DialogWindow
  if ($dialog) {
    break
  }
  Start-Sleep -Milliseconds 200
}

if (-not $dialog) {
  throw "Timed out waiting for native file chooser dialog."
}

[void][NativeWindowTools]::ShowWindow($dialog.Handle, 5)
[void][NativeWindowTools]::SetForegroundWindow($dialog.Handle)
Start-Sleep -Milliseconds 250

Set-Clipboard -Value $FilePath
[System.Windows.Forms.SendKeys]::SendWait('%n')
Start-Sleep -Milliseconds 150
[System.Windows.Forms.SendKeys]::SendWait('^v')
Start-Sleep -Milliseconds 150
[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')

Write-Output (@{
  handled = $true
  title = $dialog.Title
  class_name = $dialog.ClassName
  file_path = $FilePath
} | ConvertTo-Json -Compress)
