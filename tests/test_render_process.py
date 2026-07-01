from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import roughcut.media.render as render_module
from roughcut.media.render import _ffmpeg_base_cmd, _replace_video_encode_args_for_software, _run_process, _video_encode_args


@pytest.mark.asyncio
async def test_run_process_captures_stdout_and_stderr() -> None:
    result = await _run_process(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        timeout=10,
    )

    assert result.returncode == 0
    assert "out" in result.stdout
    assert "err" in result.stderr


@pytest.mark.asyncio
async def test_run_process_times_out() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        await _run_process(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=1,
        )


def test_render_thread_settings_are_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        render_module,
        "get_settings",
        lambda: SimpleNamespace(
            render_ffmpeg_threads=8,
            render_ffmpeg_filter_threads=4,
            render_video_encoder="libx264",
            render_cpu_preset="veryfast",
            render_crf=19,
        ),
    )

    assert _ffmpeg_base_cmd() == ["ffmpeg", "-nostdin", "-y", "-filter_threads", "4"]

    encode_args = _video_encode_args(prefer_hardware=False)
    assert encode_args[encode_args.index("-threads") + 1] == "8"


def test_hardware_fallback_caps_software_threads_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        render_module,
        "get_settings",
        lambda: SimpleNamespace(
            render_ffmpeg_threads=0,
            render_ffmpeg_filter_threads=0,
            render_video_encoder="libx264",
            render_cpu_preset="veryfast",
            render_crf=19,
        ),
    )

    fallback = _replace_video_encode_args_for_software(
        [
            "ffmpeg",
            "-i",
            "in.mp4",
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p5",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "out.mp4",
        ]
    )

    assert fallback[fallback.index("-c:v") + 1] == "libx264"
    assert fallback[fallback.index("-threads") + 1] == "4"


@pytest.mark.asyncio
async def test_render_video_skips_master_audio_filters_for_already_mastered_audio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(render_module, "_probe_duration", lambda _path: 10.0)
    monkeypatch.setattr(
        render_module,
        "_probe_video_stream",
        lambda _path: {
            "width": 1920,
            "height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_raw": 0,
            "rotation_cw": 0,
            "fps": 29.97,
        },
    )
    monkeypatch.setattr(
        render_module,
        "_resolve_delivery_frame_rate",
        lambda *, source_fps, delivery: source_fps,
    )
    monkeypatch.setattr(
        render_module,
        "_resolve_delivery_resolution",
        lambda *, expected_width, expected_height, delivery: (expected_width, expected_height),
    )
    monkeypatch.setattr(render_module, "_prefer_software_encoder_for_source", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(render_module, "_append_delivery_color_filter", lambda parts, input_label, _source_info, output_label: input_label)
    monkeypatch.setattr(render_module, "_build_segment_filter_chain", lambda *_args, **_kwargs: ([], "0:v", "0:a"))
    monkeypatch.setattr(render_module, "_build_video_transform_editing_accents", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(render_module, "_build_runtime_hyperframes_plan", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(render_module.hyperframes, "effects_from_plan", lambda _plan, fallback: fallback)
    monkeypatch.setattr(render_module.hyperframes, "overlay_plan_from_plan", lambda _plan, fallback: fallback)
    monkeypatch.setattr(
        render_module,
        "_build_master_audio_filter_chain",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("master audio filters should not run")),
    )

    async def fake_detect_video_rotation_decision(_source_path):
        return SimpleNamespace(rotation_cw=0, confidence=1.0, source="test", reason="stub", to_dict=lambda: {})

    async def fake_run_process(cmd: list[str], *, timeout: int):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    async def fake_normalize_rendered_output(*_args, **_kwargs):
        return None

    monkeypatch.setattr("roughcut.media.rotation.detect_video_rotation_decision", fake_detect_video_rotation_decision)
    monkeypatch.setattr(render_module, "_run_process", fake_run_process)
    monkeypatch.setattr(render_module, "_normalize_rendered_output", fake_normalize_rendered_output)
    monkeypatch.setattr(render_module, "_write_debug_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(render_module, "_write_debug_text", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(render_module, "_write_process_debug", lambda *_args, **_kwargs: None)

    await render_module.render_video(
        source_path=tmp_path / "source.mp4",
        render_plan=None,
        editorial_timeline={},
        output_path=tmp_path / "out.mp4",
        keep_segments=[{"type": "keep", "start": 0.0, "end": 10.0}],
        packaging_context={
            "assets": {},
            "editing_accents": {},
            "has_packaging_assets": False,
            "section_choreography": {},
            "subtitles": {},
        },
        runtime_plan_context={
            "delivery": {"frame_rate_mode": "source"},
            "video_transform": {},
            "avatar_plan": {},
            "voice_processing": {"noise_reduction": True},
            "loudness": {"target_lufs": -16.0, "peak_limit": -2.0},
            "audio_already_mastered": True,
        },
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "aresample=async=1:first_pts=0" in filter_complex
    assert "aformat=sample_rates=48000:channel_layouts=stereo[afinal]" in filter_complex
    assert "anlmdn" not in filter_complex
    assert "loudnorm" not in filter_complex
    assert "alimiter" not in filter_complex


@pytest.mark.asyncio
async def test_audio_duration_padding_extends_short_audio(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "padded.mp4"
    source.write_bytes(b"source")
    commands: list[list[str]] = []

    def fake_probe(path):
        assert path == source
        return {
            "format": {"duration": "10.0"},
            "streams": [
                {"codec_type": "video", "duration": "10.0"},
                {"codec_type": "audio", "duration": "6.0"},
            ],
        }

    async def fake_run_process(cmd: list[str], *, timeout: int):
        commands.append(cmd)
        output.write_bytes(b"padded")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render_module, "_ffprobe_json", fake_probe)
    monkeypatch.setattr(render_module, "_run_process", fake_run_process)
    monkeypatch.setattr(render_module, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_module, "_write_process_debug", lambda *args, **kwargs: None)

    result = await render_module._ensure_audio_duration_covers_video(
        source,
        output_path=output,
        debug_dir=None,
        debug_prefix="test.audio_pad",
    )

    assert result == output
    command = commands[0]
    assert "-filter_complex" in command
    assert "apad=whole_dur=10.000" in command[command.index("-filter_complex") + 1]
    assert command[command.index("-map") + 1] == "0:v:0"
    assert "-c:v" in command
    assert command[command.index("-c:v") + 1] == "copy"
    assert command[command.index("-t") + 1] == "10.000000"


@pytest.mark.asyncio
async def test_audio_duration_padding_skips_near_matching_audio(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "padded.mp4"
    source.write_bytes(b"source")

    monkeypatch.setattr(
        render_module,
        "_ffprobe_json",
        lambda _path: {
            "format": {"duration": "10.0"},
            "streams": [
                {"codec_type": "video", "duration": "10.0"},
                {"codec_type": "audio", "duration": "9.8"},
            ],
        },
    )

    async def fail_run_process(*_args, **_kwargs):
        raise AssertionError("audio padding should not run")

    monkeypatch.setattr(render_module, "_run_process", fail_run_process)

    result = await render_module._ensure_audio_duration_covers_video(
        source,
        output_path=output,
        debug_dir=None,
        debug_prefix="test.audio_pad",
    )

    assert result == source


@pytest.mark.asyncio
async def test_music_packaging_keeps_mix_duration_without_master_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = tmp_path / "source.mp4"
    music = tmp_path / "music.m4a"
    output = tmp_path / "packaged.mp4"
    source.write_bytes(b"source")
    music.write_bytes(b"music")
    commands: list[list[str]] = []

    monkeypatch.setattr(render_module, "_probe_duration", lambda _path: 10.0)
    async def fake_ensure_audio_duration_covers_video(source_path, **_kwargs):
        return source_path

    monkeypatch.setattr(render_module, "_ensure_audio_duration_covers_video", fake_ensure_audio_duration_covers_video)
    monkeypatch.setattr(render_module, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_module, "_write_process_debug", lambda *args, **kwargs: None)

    async def fake_run_process(cmd: list[str], *, timeout: int):
        commands.append(cmd)
        output.write_bytes(b"packaged")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render_module, "_run_process", fake_run_process)

    result = await render_module._apply_music_and_watermark(
        source,
        music_plan={"path": str(music), "volume": 0.12},
        watermark_plan=None,
        expected_width=1920,
        expected_height=1080,
        output_path=output,
        debug_dir=None,
    )

    assert result == output
    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "sidechaincompress" not in filter_complex
    assert "loudnorm" not in filter_complex
    assert "alimiter" not in filter_complex
    assert "[0:a][bgm_pre]amix=inputs=2:duration=first:dropout_transition=2:normalize=0" in filter_complex
    assert "aresample=async=1:first_pts=0[aout]" in filter_complex
    assert "-c:v" in commands[0]
    assert commands[0][commands[0].index("-c:v") + 1] == "libx264"
    assert commands[0][commands[0].index("-threads") + 1] == "2"
    assert "-t" in commands[0]
    assert commands[0][commands[0].index("-t") + 1] == "10.000000"


@pytest.mark.asyncio
async def test_intro_outro_normalizes_audio_to_segment_video_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = tmp_path / "source.mp4"
    intro = tmp_path / "intro.mp4"
    output = tmp_path / "with_bookends.mp4"
    source.write_bytes(b"source")
    intro.write_bytes(b"intro")
    commands: list[list[str]] = []

    async def fake_prepare_packaging_clip(_source_path, output_path, **_kwargs):
        output_path.write_bytes(b"prepared")
        return output_path

    def fake_probe_duration(path):
        return 3.0 if "intro_asset.prepared" in str(path) else 12.0

    def fake_probe_stream_duration(path, codec_type):
        if codec_type == "video" and "intro_asset.prepared" in str(path):
            return 4.0
        return fake_probe_duration(path)

    async def fake_run_process(cmd: list[str], *, timeout: int):
        commands.append(cmd)
        output.write_bytes(b"bookends")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render_module, "_prepare_packaging_clip", fake_prepare_packaging_clip)
    monkeypatch.setattr(render_module, "_probe_duration", fake_probe_duration)
    monkeypatch.setattr(render_module, "_probe_stream_duration", fake_probe_stream_duration)
    monkeypatch.setattr(render_module, "_run_process", fake_run_process)
    monkeypatch.setattr(render_module, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_module, "_write_process_debug", lambda *args, **kwargs: None)

    result = await render_module._apply_intro_outro(
        source,
        intro_plan={"path": str(intro)},
        outro_plan=None,
        expected_width=1920,
        expected_height=1080,
        output_path=output,
        debug_dir=None,
        target_fps=29.97,
    )

    assert result == output
    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "aresample=async=1:first_pts=0" in filter_complex
    assert "apad=whole_dur=4.000,atrim=start=0:end=4.000" in filter_complex
    assert "apad=whole_dur=12.000,atrim=start=0:end=12.000" in filter_complex
    assert "-c:v" in commands[0]
    assert commands[0][commands[0].index("-c:v") + 1] == "libx264"
    assert commands[0][commands[0].index("-threads") + 1] == "2"


@pytest.mark.asyncio
async def test_intro_outro_resolves_container_prefixed_windows_asset_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = tmp_path / "source.mp4"
    intro = tmp_path / "intro.mp4"
    output = tmp_path / "with_bookends.mp4"
    source.write_bytes(b"source")
    intro.write_bytes(b"intro")
    prepared_sources: list[Path] = []

    def fake_resolve_runtime_media_path(value: str) -> Path:
        if value.startswith("/app/E:/"):
            return intro
        return Path(value)

    async def fake_prepare_packaging_clip(source_path, output_path, **_kwargs):
        prepared_sources.append(source_path)
        output_path.write_bytes(b"prepared")
        return output_path

    def fake_probe_duration(path):
        return 3.0 if "intro_asset.prepared" in str(path) else 12.0

    async def fake_run_process(cmd: list[str], *, timeout: int):
        output.write_bytes(b"bookends")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(render_module, "resolve_runtime_media_path", fake_resolve_runtime_media_path)
    monkeypatch.setattr(render_module, "_prepare_packaging_clip", fake_prepare_packaging_clip)
    monkeypatch.setattr(render_module, "_probe_duration", fake_probe_duration)
    monkeypatch.setattr(render_module, "_probe_stream_duration", lambda path, codec_type: fake_probe_duration(path))
    monkeypatch.setattr(render_module, "_run_process", fake_run_process)
    monkeypatch.setattr(render_module, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_module, "_write_process_debug", lambda *args, **kwargs: None)

    result = await render_module._apply_intro_outro(
        source,
        intro_plan={"path": "/app/E:/WorkSpace/RoughCut/assets/packaging/intro/fas.mp4"},
        outro_plan=None,
        expected_width=1920,
        expected_height=1080,
        output_path=output,
        debug_dir=None,
    )

    assert result == output
    assert prepared_sources == [intro]
