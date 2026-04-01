from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _powershell_binary() -> str:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is required for docker refresh safety checks")
    return shell


def _run_powershell_wrapper(tmp_path: Path, script_text: str) -> subprocess.CompletedProcess[str]:
    wrapper = tmp_path / "refresh_safety_wrapper.ps1"
    wrapper.write_text(script_text, encoding="utf-8")
    return subprocess.run(
        [_powershell_binary(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_refresh_session_defers_when_active_work_exists(tmp_path: Path):
    script_path = json.dumps(str(Path(__file__).resolve().parents[1] / "scripts" / "run-roughcut-docker-refresh-session.ps1"))
    script_text = rf"""
$ErrorActionPreference = "Stop"
$global:dockerCalls = @()
function docker {{
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    $commandLine = $Args -join " "
    $global:dockerCalls += $commandLine
    $global:LASTEXITCODE = 0
    if ($commandLine -match '\bexec\b.*\bpostgres\b.*\bpsql\b') {{
        Write-Output "1|2"
    }} elseif ($commandLine -match '\bup\b') {{
        Write-Output "UP_CALLED"
    }}
}}
try {{
    & {script_path} -ComposeMode runtime -DryRun
    $scriptExit = 0
}} catch {{
    $scriptExit = 1
    Write-Output ("ERROR=" + $_.Exception.Message)
}}
Write-Output ("CALLS=" + ($global:dockerCalls -join " || "))
exit $scriptExit
"""

    result = _run_powershell_wrapper(tmp_path, script_text)

    assert result.returncode != 0
    assert "[DEFERRED]" in result.stdout
    assert "UP_CALLED" not in result.stdout
    assert "CALLS=" in result.stdout


def test_refresh_session_runs_when_runtime_is_idle(tmp_path: Path):
    script_path = json.dumps(str(Path(__file__).resolve().parents[1] / "scripts" / "run-roughcut-docker-refresh-session.ps1"))
    script_text = rf"""
$ErrorActionPreference = "Stop"
$global:dockerCalls = @()
function docker {{
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    $commandLine = $Args -join " "
    $global:dockerCalls += $commandLine
    $global:LASTEXITCODE = 0
    if ($commandLine -match '\bexec\b.*\bpostgres\b.*\bpsql\b') {{
        Write-Output "0|0"
    }} elseif ($commandLine -match '\bup\b') {{
        Write-Output "UP_CALLED"
    }}
}}
try {{
    & {script_path} -ComposeMode runtime
    $scriptExit = 0
}} catch {{
    $scriptExit = 1
    Write-Output ("ERROR=" + $_.Exception.Message)
}}
Write-Output ("CALLS=" + ($global:dockerCalls -join " || "))
exit $scriptExit
"""

    result = _run_powershell_wrapper(tmp_path, script_text)

    assert result.returncode == 0
    assert "UP_CALLED" in result.stdout
    assert "Docker refresh session completed successfully" in result.stdout


def test_refresh_session_defers_when_review_hold_is_active(tmp_path: Path):
    script_path = json.dumps(str(Path(__file__).resolve().parents[1] / "scripts" / "run-roughcut-docker-refresh-session.ps1"))
    hold_path = tmp_path / "runtime-refresh-hold.json"
    hold_payload = {
        "reason": "content_profile_review",
        "job_id": "00000000-0000-0000-0000-000000000001",
        "expires_at_utc": "2099-01-01T00:00:00Z",
    }
    hold_path.write_text(json.dumps(hold_payload), encoding="utf-8")
    hold_path_json = json.dumps(str(hold_path))
    script_text = rf"""
$ErrorActionPreference = "Stop"
$env:ROUGHCUT_RUNTIME_REFRESH_HOLD_PATH = {hold_path_json}
$global:dockerCalls = @()
function docker {{
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    $commandLine = $Args -join " "
    $global:dockerCalls += $commandLine
    $global:LASTEXITCODE = 0
    if ($commandLine -match '\bup\b') {{
        Write-Output "UP_CALLED"
    }}
}}
try {{
    & {script_path} -ComposeMode runtime -DryRun
    $scriptExit = 0
}} catch {{
    $scriptExit = 1
    Write-Output ("ERROR=" + $_.Exception.Message)
}}
Write-Output ("CALLS=" + ($global:dockerCalls -join " || "))
exit $scriptExit
"""

    result = _run_powershell_wrapper(tmp_path, script_text)

    assert result.returncode != 0
    assert "[DEFERRED]" in result.stdout
    assert "content_profile_review" in result.stdout
    assert "UP_CALLED" not in result.stdout


def test_watch_script_uses_longer_backoff_for_deferred_refresh():
    script_text = Path("scripts/watch-roughcut-docker-runtime.ps1").read_text(encoding="utf-8")

    assert 'Status -eq "deferred"' in script_text
    assert "AddSeconds($retryDelaySeconds)" in script_text
    assert "Docker auto-refresh deferred because active work is still running" in script_text
