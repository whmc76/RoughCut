import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.api import tools


def _write_audio(path: Path, content: bytes, *, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


def test_reference_audio_history_keeps_five_recent_unique_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    upload_root = tmp_path / "reference-uploads"
    tts_root = tmp_path / "tts"
    monkeypatch.setattr(tools, "_REFERENCE_UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(tools, "_TTS_ROOT", tts_root)
    monkeypatch.setattr(tools, "_audio_duration_seconds", lambda path: None)

    _write_audio(upload_root / "old-duplicate.wav", b"same-audio", mtime=100)
    _write_audio(tts_root / "new-duplicate.wav", b"same-audio", mtime=200)
    for index, mtime in enumerate([190, 180, 170, 160, 150, 140], start=1):
        _write_audio(upload_root / f"unique-{index}.wav", f"audio-{index}".encode(), mtime=mtime)

    items = tools._list_reference_audio_history()

    assert [item["name"] for item in items] == [
        "unique-1.wav",
        "unique-2.wav",
        "unique-3.wav",
        "unique-4.wav",
        "unique-5.wav",
    ]
    assert "old-duplicate.wav" not in {item["name"] for item in items}
    assert "new-duplicate.wav" not in {item["name"] for item in items}


def test_reference_audio_history_includes_uploaded_video_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    upload_root = tmp_path / "reference-uploads"
    monkeypatch.setattr(tools, "_REFERENCE_UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(tools, "_TTS_ROOT", tmp_path / "tts")
    monkeypatch.setattr(tools, "_audio_duration_seconds", lambda path: 12.0)

    _write_audio(upload_root / "reference.mp4", b"video-with-audio", mtime=100)

    items = tools._list_reference_audio_history()

    assert items[0]["name"] == "reference.mp4"
    assert items[0]["source"] == "参考上传"


def test_tts_output_history_is_separate_from_reference_history(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reference_root = tmp_path / "reference-uploads"
    tts_root = tmp_path / "tts"
    monkeypatch.setattr(tools, "_REFERENCE_UPLOAD_ROOT", reference_root)
    monkeypatch.setattr(tools, "_TTS_ROOT", tts_root)
    monkeypatch.setattr(tools, "_audio_duration_seconds", lambda path: None)

    _write_audio(reference_root / "voice-reference.wav", b"reference", mtime=100)
    _write_audio(tts_root / "tts-output.wav", b"output", mtime=200)

    assert [item["name"] for item in tools._list_reference_audio_history()] == ["voice-reference.wav"]
    assert [item["name"] for item in tools._list_tts_output_history()] == ["tts-output.wav"]


def test_tts_output_filename_includes_timestamp_and_config() -> None:
    filename = tools._build_tts_output_filename(
        created_at=datetime(2026, 5, 13, 7, 19, 30, tzinfo=timezone.utc),
        mode="instruct2",
        prompt_text="",
        instruct_text="请用开心、明亮、有感染力的语气说这句话。",
        spk_id="",
        zero_shot_spk_id="",
        stream=True,
        speed=1.0,
        seed=0,
        text_frontend=True,
        reference_path=Path("原始参考 voice 01.wav"),
        segment_count=3,
    )

    assert filename.startswith("tts_20260513_")
    assert "instruct2" in filename
    assert "inst-" in filename
    assert "ref-原始参考-voice-01" in filename
    assert "speed1" in filename
    assert "seed0" in filename
    assert "seg3" in filename
    assert filename.endswith(".wav")


def test_tts_output_history_reads_sidecar_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tts_root = tmp_path / "tts"
    monkeypatch.setattr(tools, "_TTS_ROOT", tts_root)
    monkeypatch.setattr(tools, "_audio_duration_seconds", lambda path: None)

    output_path = tts_root / "tts_20260513_151930_instruct2_speed1_seed0.wav"
    _write_audio(output_path, b"output", mtime=200)
    output_path.with_suffix(".wav.json").write_text(
        '{"created_at":"2026-05-13T07:19:30+00:00","display_name":"readable.wav","config_summary":"mode=instruct2 · speed=1","text_preview":"测试文本"}',
        encoding="utf-8",
    )

    item = tools._list_tts_output_history()[0]

    assert item["name"] == output_path.name
    assert item["display_name"] == "readable.wav"
    assert item["created_at"] == "2026-05-13T07:19:30+00:00"
    assert item["config_summary"] == "mode=instruct2 · speed=1"
    assert item["text_preview"] == "测试文本"


def test_safe_upload_filename_preserves_original_name_when_possible() -> None:
    assert tools._safe_upload_filename("原始参考 voice 01.m4a", fallback_suffix=".wav") == "原始参考 voice 01.m4a"
    assert tools._safe_upload_filename("bad:name?.wav", fallback_suffix=".wav") == "bad_name.wav"


def test_prepare_reference_video_extracts_audio_to_wav(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"video")
    reference_root = tmp_path / "reference-cache"
    commands: list[list[str]] = []

    monkeypatch.setattr(tools, "_REFERENCE_ROOT", reference_root)
    monkeypatch.setattr(tools, "_audio_duration_seconds", lambda path: 12.0)
    monkeypatch.setattr(tools.shutil, "which", lambda name: "ffmpeg")

    def fake_run(command, **kwargs):
        commands.append(list(command))
        Path(command[-1]).write_bytes(b"wav")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)

    prepared = tools._prepare_reference_audio_for_cosyvoice(source, run_id="run-test")

    assert prepared.parent == reference_root
    assert prepared.suffix == ".wav"
    assert commands[0][:4] == ["ffmpeg", "-y", "-i", str(source)]
    assert "-vn" in commands[0]
    assert "-ar" in commands[0]
    assert "16000" in commands[0]
    assert "-t" not in commands[0]


def test_prepare_long_reference_audio_trims_to_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "reference.wav"
    source.write_bytes(b"wav")
    commands: list[list[str]] = []

    monkeypatch.setattr(tools, "_REFERENCE_ROOT", tmp_path / "reference-cache")
    monkeypatch.setattr(tools, "_audio_duration_seconds", lambda path: 45.0)
    monkeypatch.setattr(tools.shutil, "which", lambda name: "ffmpeg")

    def fake_run(command, **kwargs):
        commands.append(list(command))
        Path(command[-1]).write_bytes(b"wav")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(tools.subprocess, "run", fake_run)

    prepared = tools._prepare_reference_audio_for_cosyvoice(source, run_id="run-test")

    assert prepared != source
    assert "-t" in commands[0]
    assert str(tools._MAX_REFERENCE_AUDIO_SEC) in commands[0]
