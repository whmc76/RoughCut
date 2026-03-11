@echo off
setlocal
set SCRIPT_DIR=%~dp0
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%stop_roughcut.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%stop_roughcut.ps1"
)
if not %ERRORLEVEL%==0 (
  echo.
  echo stop_roughcut failed with exit code %ERRORLEVEL%.
  pause
)
endlocal
