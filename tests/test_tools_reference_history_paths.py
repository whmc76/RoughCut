from fastapi import HTTPException

from roughcut.api import tools


def test_resolve_reference_audio_history_path_accepts_legacy_f_drive_root(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    reference_root = runtime_root / "tools" / "reference-uploads"
    reference_root.mkdir(parents=True)
    reference = reference_root / "voice.wav"
    reference.write_bytes(b"RIFF")

    monkeypatch.setattr(tools, "DEFAULT_OUTPUT_ROOT", runtime_root)
    monkeypatch.setattr(tools, "_REFERENCE_UPLOAD_ROOT", reference_root)

    resolved = tools._resolve_reference_audio_history_path(r"F:\roughcut_outputs\tools\reference-uploads\voice.wav")

    assert resolved == reference.resolve()


def test_resolve_reference_audio_history_path_rejects_missing_legacy_file(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    reference_root = runtime_root / "tools" / "reference-uploads"
    reference_root.mkdir(parents=True)

    monkeypatch.setattr(tools, "DEFAULT_OUTPUT_ROOT", runtime_root)
    monkeypatch.setattr(tools, "_REFERENCE_UPLOAD_ROOT", reference_root)

    try:
        tools._resolve_reference_audio_history_path(r"F:\roughcut_outputs\tools\reference-uploads\missing.wav")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected missing legacy reference path to be rejected")


def test_tts_output_config_normalizes_existing_legacy_reference_path(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    reference_root = runtime_root / "tools" / "reference-uploads"
    reference_root.mkdir(parents=True)
    reference = reference_root / "voice.wav"
    reference.write_bytes(b"RIFF")

    monkeypatch.setattr(tools, "DEFAULT_OUTPUT_ROOT", runtime_root)

    normalized = tools._normalize_tts_output_config(
        {"reference_audio": "F:/roughcut_outputs/tools/reference-uploads/voice.wav", "mode": "instruct2"}
    )

    assert normalized["reference_audio"] == str(reference)
    assert normalized["mode"] == "instruct2"
