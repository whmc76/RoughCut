@echo off
setlocal
set SCRIPT_DIR=%~dp0

if /I "%~1"=="dev" goto pnpm_dev
if /I "%~1"=="build" goto pnpm_build
if /I "%~1"=="test" goto pnpm_test
if /I "%~1"=="setup" goto pnpm_setup
if /I "%~1"=="doctor" goto pnpm_doctor
if /I "%~1"=="migrate" goto pnpm_migrate
if /I "%~1"=="docker-up" goto pnpm_docker_up
if /I "%~1"=="docker-down" goto pnpm_docker_down
if /I "%~1"=="help" goto usage

goto powershell_start

:require_pnpm
where pnpm >nul 2>nul
if %ERRORLEVEL%==0 goto :eof
echo.
echo pnpm is required for this command. Enable Corepack or install pnpm first.
set EXIT_CODE=1
goto finish

:pnpm_dev
call :require_pnpm
if not %ERRORLEVEL%==0 goto finish
call pnpm dev
set EXIT_CODE=%ERRORLEVEL%
goto finish

:pnpm_build
call :require_pnpm
if not %ERRORLEVEL%==0 goto finish
call pnpm build
set EXIT_CODE=%ERRORLEVEL%
goto finish

:pnpm_test
call :require_pnpm
if not %ERRORLEVEL%==0 goto finish
call pnpm test
set EXIT_CODE=%ERRORLEVEL%
goto finish

:pnpm_setup
call :require_pnpm
if not %ERRORLEVEL%==0 goto finish
call pnpm setup
set EXIT_CODE=%ERRORLEVEL%
goto finish

:pnpm_doctor
call :require_pnpm
if not %ERRORLEVEL%==0 goto finish
call pnpm doctor
set EXIT_CODE=%ERRORLEVEL%
goto finish

:pnpm_migrate
call :require_pnpm
if not %ERRORLEVEL%==0 goto finish
call pnpm migrate
set EXIT_CODE=%ERRORLEVEL%
goto finish

:pnpm_docker_up
call :require_pnpm
if not %ERRORLEVEL%==0 goto finish
call pnpm docker:up
set EXIT_CODE=%ERRORLEVEL%
goto finish

:pnpm_docker_down
call :require_pnpm
if not %ERRORLEVEL%==0 goto finish
call pnpm docker:down
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_start
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%restart_roughcut.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%restart_roughcut.ps1"
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:usage
echo.
echo RoughCut Windows entrypoint
echo.
echo   restart_roughcut.bat            One-click detached startup package
echo   restart_roughcut.bat dev        Run unified pnpm dev
echo   restart_roughcut.bat build      Run pnpm build
echo   restart_roughcut.bat test       Run pnpm test
echo   restart_roughcut.bat setup      Run pnpm setup
echo   restart_roughcut.bat doctor     Run pnpm doctor
echo   restart_roughcut.bat migrate    Run pnpm migrate
echo   restart_roughcut.bat docker-up  Run pnpm docker:up
echo   restart_roughcut.bat docker-down Run pnpm docker:down
set EXIT_CODE=0

:finish
if not "%EXIT_CODE%"=="0" (
  echo.
  echo restart_roughcut failed with exit code %EXIT_CODE%.
  pause
)
endlocal
exit /b %EXIT_CODE%
