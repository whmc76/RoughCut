from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = REPO_ROOT / "start_roughcut.ps1"


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
    assert '"MOSS-TTSD"' in body
    assert "Get-MossTtsBaseUrl" in body
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


def test_moss_tts_probe_uses_config_or_roughcut_compose_port() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")
    body = _function_body(source, "Get-MossTtsBaseUrl")

    assert '"MOSS_TTS_API_BASE_URL"' in body
    assert '"http://127.0.0.1:30190"' in body
    assert 'Resolve-ContainerMappedPort -ContainerName "moss-ttsd" -ContainerPort 30000' in body
    assert "Get-BaseUrlWithPort" in body


def test_local_start_checks_configured_service_probes_once() -> None:
    source = START_SCRIPT.read_text(encoding="utf-8")

    assert "Test-RoughCutConfiguredStartupServices" in source
    assert 'Wait-LocalPortListening -TestPort $servicePorts.HeygemApi -ServiceName "HeyGem API (external)"' not in source
    assert 'Wait-LocalPortListening -TestPort $servicePorts.HeygemTraining -ServiceName "IndexTTS2"' not in source
