@echo off
setlocal
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if /I "%~1"=="dev" goto pnpm_dev
if /I "%~1"=="infra" goto powershell_infra
if /I "%~1"=="runtime" goto powershell_runtime
if /I "%~1"=="runtime-local-asr" goto powershell_runtime_local_asr
if /I "%~1"=="full" goto powershell_full
if /I "%~1"=="full-local-asr" goto powershell_full_local_asr
if /I "%~1"=="runtime-down" goto powershell_runtime_down
if /I "%~1"=="full-down" goto powershell_full_down
if /I "%~1"=="runtime-watch" goto powershell_runtime_watch
if /I "%~1"=="full-watch" goto powershell_full_watch
if /I "%~1"=="build" goto pnpm_build
if /I "%~1"=="test" goto pnpm_test
if /I "%~1"=="clip-test" goto pnpm_test_clip
if /I "%~1"=="setup" goto pnpm_setup
if /I "%~1"=="doctor" goto pnpm_doctor
if /I "%~1"=="migrate" goto pnpm_migrate
if /I "%~1"=="docker-up" goto pnpm_docker_up
if /I "%~1"=="docker-down" goto pnpm_docker_down
if /I "%~1"=="StopOnly" goto powershell_stoponly
if /I "%~1"=="--StopOnly" goto powershell_stoponly
if /I "%~1"=="/StopOnly" goto powershell_stoponly
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

:pnpm_test_clip
call :require_pnpm
if not %ERRORLEVEL%==0 goto finish
shift
call pnpm test:clip -- %*
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
set "POWER_ARGS=%*"
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" %POWER_ARGS%
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" %POWER_ARGS%
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_infra
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode infra
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode infra
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_runtime
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode runtime
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode runtime
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_runtime_local_asr
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode runtime -DockerPythonExtras local-asr
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode runtime -DockerPythonExtras local-asr
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_full
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode full
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode full
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_full_local_asr
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode full -DockerPythonExtras local-asr
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode full -DockerPythonExtras local-asr
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_runtime_down
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode runtime-down
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode runtime-down
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_full_down
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode full-down
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -Mode full-down
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_runtime_watch
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\watch-roughcut-docker-runtime.ps1" -ComposeMode runtime
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\watch-roughcut-docker-runtime.ps1" -ComposeMode runtime
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_full_watch
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\watch-roughcut-docker-runtime.ps1" -ComposeMode full
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\watch-roughcut-docker-runtime.ps1" -ComposeMode full
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:powershell_stoponly
where pwsh >nul 2>nul
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -StopOnly
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_roughcut.ps1" -StopOnly
)
set EXIT_CODE=%ERRORLEVEL%
goto finish

:usage
echo.
echo RoughCut Windows entrypoint
echo.
echo   start_roughcut.bat             One-click startup package
echo   start_roughcut.bat infra       Start only PostgreSQL / Redis / MinIO containers
echo   start_roughcut.bat runtime     Start recommended always-on Docker runtime and auto-start workspace watch
echo   start_roughcut.bat runtime-local-asr  Start runtime with local-asr extras enabled inside Docker
echo   start_roughcut.bat full        Start runtime plus automation services and auto-start workspace watch
echo   start_roughcut.bat full-local-asr     Start full stack with local-asr extras enabled inside Docker
echo   start_roughcut.bat runtime-down Stop runtime and its workspace watch
echo   start_roughcut.bat full-down    Stop runtime plus automation and their workspace watch
echo   start_roughcut.bat runtime-watch  Watch workspace changes and auto-refresh Docker runtime
echo   start_roughcut.bat full-watch     Watch workspace changes and auto-refresh runtime + automation
echo   start_roughcut.bat dev         Run unified pnpm dev
echo   start_roughcut.bat build       Run pnpm build
echo   start_roughcut.bat test        Run pnpm test
echo   start_roughcut.bat clip-test   Run one manual clip test with a chosen source
echo   start_roughcut.bat setup       Run pnpm setup
echo   start_roughcut.bat doctor      Run pnpm doctor
echo   start_roughcut.bat migrate     Run pnpm migrate
echo   start_roughcut.bat docker-up   Run pnpm docker:up
echo   start_roughcut.bat docker-down Run pnpm docker:down
set EXIT_CODE=0

:finish
if not "%EXIT_CODE%"=="0" (
  echo.
  echo start_roughcut failed with exit code %EXIT_CODE%.
  pause
)
endlocal
exit /b %EXIT_CODE%
