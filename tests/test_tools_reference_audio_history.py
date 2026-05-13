import os
from contextlib import asynccontextmanager
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


def test_reference_audio_history_reads_bound_prompt_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    upload_root = tmp_path / "reference-uploads"
    monkeypatch.setattr(tools, "_REFERENCE_UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(tools, "_TTS_ROOT", tmp_path / "tts")
    monkeypatch.setattr(tools, "_audio_duration_seconds", lambda path: 12.0)

    reference = upload_root / "voice.wav"
    _write_audio(reference, b"voice", mtime=100)
    tools._write_reference_audio_metadata(
        reference,
        prompt_text="  参考音频里实际说过的话。\n第二句。  ",
        prompt_text_source="manual",
        provider="moss_tts",
        mode="moss_voice_clone",
    )

    item = tools._list_reference_audio_history()[0]

    assert item["name"] == "voice.wav"
    assert item["prompt_text"] == "参考音频里实际说过的话。 第二句。"
    assert item["prompt_text_source"] == "manual"
    assert item["text_preview"] == "参考音频里实际说过的话。 第二句。"
    assert item["config"] == {"provider": "moss_tts", "mode": "moss_voice_clone", "prompt_text_source": "manual"}
    assert tools._read_reference_audio_prompt_text(reference) == "参考音频里实际说过的话。 第二句。"


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


def test_moss_tts_prompt_text_adds_duration_token() -> None:
    prompt = tools._build_moss_tts_prompt_text("测试 MOSS TTS。", mode="moss_duration_control", duration_tokens=180)

    assert prompt == "${token:180}测试 MOSS TTS。"


def test_moss_tts_prompt_text_applies_duration_token_to_normal_tts() -> None:
    prompt = tools._build_moss_tts_prompt_text("测试 MOSS TTS。", mode="moss_direct_tts", duration_tokens=180)

    assert prompt == "${token:180}测试 MOSS TTS。"


def test_moss_tts_podcast_text_gets_default_speaker_tag() -> None:
    prompt = tools._build_moss_tts_prompt_text("欢迎来到今天的节目。", mode="moss_podcast", duration_tokens=0)

    assert prompt == "[S1] 欢迎来到今天的节目。"


def test_moss_tts_podcast_keeps_existing_speaker_tags() -> None:
    prompt = tools._build_moss_tts_prompt_text("[S1] 你好。[S2] 你好。", mode="moss_podcast", duration_tokens=0)

    assert prompt == "[S1] 你好。[S2] 你好。"


def test_moss_tts_sound_effect_prompt_uses_ambient_sound_control() -> None:
    prompt = tools._build_moss_tts_prompt_text("海边浪声和远处人群。", mode="moss_sound_effect", duration_tokens=90)

    assert prompt == "${token:90}${ambient_sound:海边浪声和远处人群。}"


def test_moss_tts_voice_clone_prompt_text_prefixes_reference_transcript() -> None:
    prompt = tools._build_moss_tts_prompt_text(
        "这是一段新文本。",
        mode="moss_voice_clone",
        duration_tokens=0,
        prompt_text="参考音频里说过的话。",
        has_reference_audio=True,
    )

    assert prompt == "[S1] 参考音频里说过的话。\n[S1] 这是一段新文本。"


def test_moss_tts_voice_clone_duration_token_applies_to_target_text_only() -> None:
    prompt = tools._build_moss_tts_prompt_text(
        "这是一段新文本。",
        mode="moss_voice_clone",
        duration_tokens=180,
        prompt_text="参考音频里说过的话。",
        has_reference_audio=True,
    )

    assert prompt == "[S1] 参考音频里说过的话。\n${token:180}[S1] 这是一段新文本。"


@pytest.mark.asyncio
async def test_reference_prompt_text_auto_asr_uses_local_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"wav-data")

    class FakeLocalHTTPASRProvider:
        async def transcribe(self, audio_path: Path, *, language: str, prompt: str | None = None, progress_callback=None):
            assert audio_path == reference
            assert language == "zh-CN"
            assert prompt is None
            if progress_callback is not None:
                progress_callback({"phase": "transcribe", "progress": 0.5})
            return SimpleNamespace(text="参考音频自动识别文本。")

    @asynccontextmanager
    async def fake_hold(*args, **kwargs):
        yield

    monkeypatch.setattr(tools, "LocalHTTPASRProvider", FakeLocalHTTPASRProvider)
    monkeypatch.setattr(tools, "hold_managed_gpu_services_async", fake_hold)

    text, source = await tools._resolve_reference_prompt_text_from_asr(
        "test-run",
        reference_path=reference,
        enabled=True,
        provider_label="MOSS-TTSD",
    )

    assert text == "参考音频自动识别文本。"
    assert source == "auto_asr"


@pytest.mark.asyncio
async def test_reference_prompt_text_auto_asr_reads_transcript_segments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"wav-data")

    class FakeLocalHTTPASRProvider:
        async def transcribe(self, audio_path: Path, *, language: str, prompt: str | None = None, progress_callback=None):
            del audio_path, language, prompt, progress_callback
            return SimpleNamespace(
                segments=[
                    SimpleNamespace(text="第一段参考文本。"),
                    SimpleNamespace(text="第二段参考文本。"),
                ]
            )

    @asynccontextmanager
    async def fake_hold(*args, **kwargs):
        yield

    monkeypatch.setattr(tools, "LocalHTTPASRProvider", FakeLocalHTTPASRProvider)
    monkeypatch.setattr(tools, "hold_managed_gpu_services_async", fake_hold)

    text, source = await tools._resolve_reference_prompt_text_from_asr(
        "test-run",
        reference_path=reference,
        enabled=True,
        provider_label="MOSS-TTSD",
    )

    assert text == "第一段参考文本。 第二段参考文本。"
    assert source == "auto_asr"


@pytest.mark.asyncio
async def test_prepared_reference_prompt_text_reasrs_shortened_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_audio = tmp_path / "source.m4a"
    prepared_audio = tmp_path / "prepared.wav"
    source_audio.write_bytes(b"source")
    prepared_audio.write_bytes(b"prepared")

    durations = {
        source_audio: 36.4,
        prepared_audio: 16.0,
    }

    class FakeLocalHTTPASRProvider:
        async def transcribe(self, audio_path: Path, *, language: str, prompt: str | None = None, progress_callback=None):
            del language, prompt, progress_callback
            assert audio_path == prepared_audio
            return SimpleNamespace(text="实际短参考音频文本。")

    @asynccontextmanager
    async def fake_hold(*args, **kwargs):
        yield

    monkeypatch.setattr(tools, "_audio_duration_seconds", lambda path: durations.get(path))
    monkeypatch.setattr(tools, "LocalHTTPASRProvider", FakeLocalHTTPASRProvider)
    monkeypatch.setattr(tools, "hold_managed_gpu_services_async", fake_hold)

    text, source = await tools._resolve_prompt_text_for_prepared_reference(
        "test-run",
        source_reference_path=source_audio,
        reference_path=prepared_audio,
        prompt_text="完整原始参考音频文本，包含裁剪后不存在的尾巴。",
        enabled=False,
        provider_label="MOSS-TTSD",
    )

    assert text == "实际短参考音频文本。"
    assert source == "auto_asr_prepared_reference"


@pytest.mark.asyncio
async def test_prepared_reference_prompt_text_reasrs_converted_audio_even_when_duration_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_audio = tmp_path / "source.m4a"
    prepared_audio = tmp_path / "prepared.wav"
    source_audio.write_bytes(b"source")
    prepared_audio.write_bytes(b"prepared")

    durations = {
        source_audio: 12.0,
        prepared_audio: 11.8,
    }

    class FakeLocalHTTPASRProvider:
        async def transcribe(self, audio_path: Path, *, language: str, prompt: str | None = None, progress_callback=None):
            del language, prompt, progress_callback
            assert audio_path == prepared_audio
            return SimpleNamespace(text="转换后实际参考文本。")

    @asynccontextmanager
    async def fake_hold(*args, **kwargs):
        yield

    monkeypatch.setattr(tools, "_audio_duration_seconds", lambda path: durations.get(path))
    monkeypatch.setattr(tools, "LocalHTTPASRProvider", FakeLocalHTTPASRProvider)
    monkeypatch.setattr(tools, "hold_managed_gpu_services_async", fake_hold)

    text, source = await tools._resolve_prompt_text_for_prepared_reference(
        "test-run",
        source_reference_path=source_audio,
        reference_path=prepared_audio,
        prompt_text="用户手填但需要校准的参考文本。",
        enabled=False,
        provider_label="MOSS-TTSD",
    )

    assert text == "转换后实际参考文本。"
    assert source == "auto_asr_prepared_reference"


def test_reference_prompt_text_keeps_manual_text_when_original_audio_is_used(tmp_path: Path) -> None:
    source_audio = tmp_path / "source.wav"
    source_audio.write_bytes(b"source")

    assert not tools._reference_audio_needs_prompt_text_calibration(source_audio, source_audio)


@pytest.mark.asyncio
async def test_post_moss_tts_request_sends_reference_audio_list(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"wav-data")
    captured: dict[str, object] = {}

    class FakeClient:
        async def post(self, url: str, *, json: dict[str, object]):
            captured["url"] = url
            captured["json"] = json
            return SimpleNamespace()

    await tools._post_moss_tts_segment_request(
        FakeClient(),
        "http://example.test/generate",
        text="测试 MOSS TTS。",
        mode="moss_voice_clone",
        duration_tokens=125,
        sampling_params={"max_new_tokens": 2048},
        reference_path=reference,
        prompt_text="参考音频文本。",
    )

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["text"] == "[S1] 参考音频文本。\n${token:125}[S1] 测试 MOSS TTS。"
    assert payload["audio_data"] == ["data:audio/wav;base64,d2F2LWRhdGE="]


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
