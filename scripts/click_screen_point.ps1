param(
  [Parameter(Mandatory = $true)]
  [double]$X,

  [Parameter(Mandatory = $true)]
  [double]$Y
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class NativeMouseTools {
  [DllImport("user32.dll")]
  public static extern bool SetCursorPos(int X, int Y);

  [DllImport("user32.dll")]
  public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}
"@

$xInt = [Math]::Max(0, [int][Math]::Round($X))
$yInt = [Math]::Max(0, [int][Math]::Round($Y))

[void][NativeMouseTools]::SetCursorPos($xInt, $yInt)
Start-Sleep -Milliseconds 120
[NativeMouseTools]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 60
[NativeMouseTools]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)

Write-Output (@{
  clicked = $true
  x = $xInt
  y = $yInt
} | ConvertTo-Json -Compress)
