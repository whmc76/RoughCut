from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = REPO_ROOT / "start_roughcut.ps1"
START_BAT = REPO_ROOT / "start_roughcut.bat"


def _function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.index(marker)
    next_function = source.find("\nfunction ", start + len(marker))
    if next_function == -1:
        return source[start:]
    return source[start:next_function]


def test_stop_roughcut_process_uses_process_name_guard() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Stop-RoughCutProcess")

    assert "Get-ProcessMatches -Pattern $Pattern" in body
    assert "Get-CimInstance Win32_Process" not in body


def test_process_match_guard_only_targets_roughcut_runtime_processes() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Get-ProcessMatches")

    assert "IsNullOrWhiteSpace($Pattern)" in body
    assert '".*"' in body
    assert '"^.*$"' in body
    assert "Refusing to match RoughCut processes with unsafe pattern" in body
    assert "$_.Name -in" in body
    for process_name in ("python.exe", "pythonw.exe", "roughcut.exe", "celery.exe"):
        assert f'"{process_name}"' in body


def test_local_api_startup_prints_192_168_lan_url() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    lan_body = _function_body(source, "Test-RoughCutLanIpv4Address")
    api_match_body = _function_body(source, "Get-RoughCutApiCommandMatchPattern")

    assert '$ApiBindHost = "0.0.0.0"' in source
    assert '"--host", $ApiBindHost' in source
    assert "LAN URL (192.168)" in source
    assert "Get-RoughCutApiLanUrls -ApiPort $Port" in source
    assert "$bytes[0] -eq 192 -and $bytes[1] -eq 168" in lan_body
    assert "127\\.0\\.0\\.1|0\\.0\\.0\\.0" in api_match_body


def test_batch_default_launches_docker_full_dev_mode() -> None:
    source = START_BAT.read_text(encoding="utf-8")

    assert "goto powershell_default_full" in source
    assert "start_roughcut.ps1\" -Mode full %POWER_ARGS%" in source
    assert "start_roughcut.ps1\" -Mode local" in source


def test_batch_test_alias_launches_docker_full_with_frontend_dev() -> None:
    source = START_BAT.read_text(encoding="utf-8")

    assert 'if /I "%~1"=="test" goto powershell_full_test' in source
    assert 'if /I "%~1"=="full-test" goto powershell_full_test' in source
    assert 'if /I "%~1"=="runtime-test" goto powershell_runtime_test' in source
    assert 'start_roughcut.ps1" -Mode full -FrontendDev' in source
    assert 'start_roughcut.ps1" -Mode runtime -FrontendDev' in source


def test_powershell_default_launches_docker_full_dev_mode() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert '[string]$Mode = "full"' in source


def test_docker_full_dev_build_is_explicit_only() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Start-RoughCutComposeMode")

    assert '$upArgs = @("up", "-d")' in body
    assert "$shouldBuild = $BuildDocker" in body
    assert "$shouldBuild = $BuildDocker -or" not in body
    assert '@("up", "-d", "--build")' in body
    assert "Retrying once with --build" not in body


def test_docker_start_does_not_remove_orphan_shared_services() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Start-RoughCutComposeMode")

    assert "--remove-orphans" not in body


def test_package_default_docker_scripts_use_full_dev_with_ports_env() -> None:
    source = (REPO_ROOT / "package.json").read_text(encoding="utf-8")

    assert '"docker:up": "pnpm docker:dev:up"' in source
    assert '"docker:down": "pnpm docker:dev:down"' in source
    assert '"docker:logs": "pnpm docker:dev:logs"' in source
    assert '"docker:dev:up": "pwsh -NoProfile -File start_roughcut.ps1 -Mode full"' in source
    assert '"docker:dev:rebuild": "pwsh -NoProfile -File start_roughcut.ps1 -Mode full -BuildDocker"' in source
    assert "docker compose --env-file roughcut.ports.env -f docker-compose.infra.yml -f docker-compose.runtime.yml -f docker-compose.dev.yml -f docker-compose.automation.yml logs -f" in source


def test_docker_compose_mounts_whole_runtime_root_inside_container() -> None:
    for compose_name in ("docker-compose.yml", "docker-compose.runtime.yml"):
        source = (REPO_ROOT / compose_name).read_text(encoding="utf-8")

        assert "ROUGHCUT_OUTPUT_ROOT: /app/data" in source
        assert "ROUGHCUT_TEST_OUTPUT_ROOT: /app/data/tests" in source
        assert "TELEGRAM_AGENT_STATE_DIR: /app/data/telegram-agent" in source
        assert "${ROUGHCUT_OUTPUT_HOST_ROOT:-./data/runtime}:/app/data" in source


def test_automation_compose_mounts_runtime_root_inside_container() -> None:
    source = (REPO_ROOT / "docker-compose.automation.yml").read_text(encoding="utf-8")

    assert "ROUGHCUT_OUTPUT_ROOT: /app/data" in source
    assert "ROUGHCUT_TEST_OUTPUT_ROOT: /app/data/tests" in source
    assert "JOB_STORAGE_DIR: /app/data/jobs" in source
    assert "TELEGRAM_AGENT_STATE_DIR: /app/data/telegram-agent" in source
    assert "${ROUGHCUT_OUTPUT_HOST_ROOT:-./data/runtime}:/app/data" in source


def test_docker_compose_overrides_host_local_service_urls_for_containers() -> None:
    for compose_name in ("docker-compose.yml", "docker-compose.runtime.yml", "docker-compose.automation.yml"):
        source = (REPO_ROOT / compose_name).read_text(encoding="utf-8")

        assert "COSYVOICE3_TTS_API_BASE_URL: ${ROUGHCUT_DOCKER_COSYVOICE3_TTS_API_BASE_URL:-http://cosyvoice3-tts:8080}" in source
        assert "MOSS_TTS_LOCAL_API_BASE_URL: ${ROUGHCUT_DOCKER_MOSS_TTS_LOCAL_API_BASE_URL:-http://moss-tts-local:8080}" in source
        assert "SEARXNG_URL: ${ROUGHCUT_DOCKER_SEARXNG_URL:-http://host.docker.internal:8080}" in source
        assert "PUBLICATION_BROWSER_AGENT_BASE_URL: ${ROUGHCUT_DOCKER_PUBLICATION_BROWSER_AGENT_BASE_URL:-http://host.docker.internal:49310}" in source


def test_autostart_installs_windows_logon_full_dev_without_build() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Install-RoughCutDockerAutostart")

    assert "$DockerAutostartTaskName = \"RoughCut Docker Dev\"" in source
    assert "-Mode full" in body
    assert "-BuildDocker" not in body
    assert "/SC ONLOGON" in body
    assert "/RL LIMITED" in body


def test_frontend_lan_urls_are_preserved_as_an_array() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert "$frontendLanUrls = @(if ($NoFrontendDev)" in source
    assert "Get-RoughCutFrontendLanUrls -FrontendPort $resolvedFrontendDevPort" in source


def test_docker_frontend_dev_session_attaches_vite_to_compose_api() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Start-RoughCutDockerFrontendDevSession")

    assert "Resolve-ContainerMappedPort -ContainerName \"roughcut-api-1\" -ContainerPort 8000" in source
    assert "Start-RoughCutFrontendDevServer -FrontendPort $resolvedFrontendDevPort -ApiPort $apiPort" in body
    assert "Wait-RoughCutHttpServiceReady -ServiceName \"Frontend dev server\"" in body
    assert "Wait-LauncherClose" in body


def test_launcher_supervisor_restarts_exited_processes() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Wait-LauncherClose")

    assert "If a managed service exits, this launcher will automatically restart it." in body
    assert "$($entry.Name) exited with code $($entry.LastExitCode)." in body
    assert "Schedule-RoughCutManagedProcessRestart -Entry $entry" in body
    assert "Restart-RoughCutManagedProcess -Entry $entry" in body
    assert "$notified" not in body


def test_managed_process_specs_keep_restart_arguments() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    process_body = _function_body(source, "Start-RoughCutProcess")
    pnpm_body = _function_body(source, "Start-RoughCutPnpmProcess")
    restart_body = _function_body(source, "Restart-RoughCutManagedProcess")

    assert "Start-RoughCutManagedProcessFromSpec -Spec $spec" in process_body
    assert "Add-RoughCutManagedProcess -Name $Name -Process $process -Spec $spec" in process_body
    assert 'Arguments = @("/d", "/s", "/c", $command)' in pnpm_body
    assert "Environment = $environmentCopy" in pnpm_body
    assert "Schedule-RoughCutManagedProcessRestart" in source
    assert "Start-RoughCutManagedProcessFromSpec -Spec $Entry.Spec" in restart_body
    assert "supervisor reattached" in restart_body


def test_worker_celery_fallback_pattern_is_not_split_into_wildcard_entry() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Start-RoughCutWorkerProcess")

    assert '("{0}.*{1}" -f' in body
    assert '[regex]::Escape("celery -A roughcut.pipeline.celery_app:celery_app worker --queues=$Queue") + ".*" + [regex]::Escape($workerNode)' not in body


def test_indextts2_startup_probe_is_gated_by_active_voice_provider() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Test-IndexTTS2StartupProbeEnabled")

    assert 'return $voiceProvider -eq "indextts2"' in body
    assert "INDEXTTS2_API_PORT" not in body
    assert "HEYGEM_TRAINING_API_PORT" not in body


def test_startup_service_probes_are_derived_from_configured_services() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Get-RoughCutStartupServiceProbes")

    assert "Get-ConfiguredTranscriptionProvider" in body
    assert '"LOCAL_ASR_API_BASE_URL"' in body
    assert '"CosyVoice3 TTS"' in body
    assert "Get-CosyVoice3TtsBaseUrl" in body
    assert '"MOSS-TTS Local"' in body
    assert "Get-MossTtsLocalBaseUrl" in body
    assert "Get-ConfiguredVoiceProvider" in body
    assert '"VOICE_CLONE_API_BASE_URL"' in body
    assert '"runninghub"' in body


def test_cosyvoice3_probe_uses_config_or_roughcut_compose_port() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Get-CosyVoice3TtsBaseUrl")

    assert '"COSYVOICE3_TTS_API_BASE_URL"' in body
    assert '"http://127.0.0.1:30180"' in body
    assert 'Resolve-ContainerMappedPort -ContainerName "cosyvoice3-tts" -ContainerPort 8080' in body
    assert "Get-BaseUrlWithPort" in body


def test_moss_tts_local_probe_uses_config_or_roughcut_compose_port() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Get-MossTtsLocalBaseUrl")

    assert '"MOSS_TTS_LOCAL_API_BASE_URL"' in body
    assert '"http://127.0.0.1:30191"' in body
    assert 'Resolve-ContainerMappedPort -ContainerName "moss-tts-local" -ContainerPort 8080' in body
    assert "Get-BaseUrlWithPort" in body


def test_local_start_checks_configured_service_probes_once() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert "Test-RoughCutConfiguredStartupServices" in source
    assert 'Wait-LocalPortListening -TestPort $servicePorts.HeygemApi -ServiceName "HeyGem API (external)"' not in source
    assert 'Wait-LocalPortListening -TestPort $servicePorts.HeygemTraining -ServiceName "IndexTTS2"' not in source
