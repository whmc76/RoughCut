from __future__ import annotations
from pathlib import Path

import pytest

from roughcut.media.render import (
    _apply_music_and_watermark,
    _build_master_audio_filter_chain,
    _build_overlay_only_editing_accents,
    _build_sound_effect_filters,
    _build_smart_effect_video_filters,
    _concat_prepared_bookends,
    _materialize_long_filter_complex_args,
    _resolve_effect_overlay_tokens,
    _resolve_delivery_resolution,
    _resolve_video_encoder,
    _resolve_smart_effect_video_tokens,
    _stage_packaging_source,
    _should_apply_smart_effect_video_transforms,
    _video_encode_args,
    render_video,
)


@pytest.mark.asyncio
async def test_apply_music_and_watermark_keys_out_white_background_when_not_preprocessed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    captured: dict[str, object] = {}

    async def fake_run_process(cmd: list[str], timeout: int):
        captured["cmd"] = cmd

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    watermark = tmp_path / "logo.jpg"
    watermark.write_bytes(b"jpg")
    output = tmp_path / "out.mp4"

    await _apply_music_and_watermark(
        source,
        music_plan=None,
        watermark_plan={
            "path": str(watermark),
            "position": "top_right",
            "opacity": 0.82,
            "scale": 0.16,
            "watermark_preprocessed": False,
        },
        expected_width=736,
        expected_height=992,
        output_path=output,
        debug_dir=None,
    )

    filter_complex = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "colorkey=0xF8F8F8:0.20:0.08" in filter_complex


def test_smart_effect_video_transforms_are_disabled_for_picture_in_picture_avatar():
    assert _should_apply_smart_effect_video_transforms({"integration_mode": "picture_in_picture"}) is False
    assert _should_apply_smart_effect_video_transforms({"integration_mode": "full_frame"}) is True


def test_build_overlay_only_editing_accents_strips_transitions():
    accents = _build_overlay_only_editing_accents(
        {
            "style": "smart_effect_punch",
            "transitions": {"enabled": True},
            "emphasis_overlays": [{"text": "重点", "start_time": 1.0, "end_time": 1.6}],
            "sound_effects": [{"start_time": 1.0, "duration_sec": 0.08}],
        }
    )

    assert accents["style"] == "smart_effect_punch"
    assert "transitions" not in accents
    assert accents["emphasis_overlays"][0]["text"] == "重点"
    assert accents["sound_effects"][0]["duration_sec"] == 0.08


def test_ai_effect_tokens_are_more_aggressive_than_packaged_defaults():
    punch_overlay = _resolve_effect_overlay_tokens("smart_effect_punch")
    ai_overlay = _resolve_effect_overlay_tokens("smart_effect_commercial_ai")
    punch_video = _resolve_smart_effect_video_tokens("smart_effect_punch")
    ai_video = _resolve_smart_effect_video_tokens("smart_effect_commercial_ai")

    assert ai_overlay["fontsize"] > punch_overlay["fontsize"]
    assert ai_overlay["boxborderw"] > punch_overlay["boxborderw"]
    assert ai_video["max_full_transforms"] == 2
    assert ai_video["pre_scale"] < punch_video["pre_scale"]
    assert ai_video["zoom_peak"] < punch_video["zoom_peak"]
    assert ai_video["flash_color"] == "0xfff2cc@0.14"


def test_ai_effect_video_filters_limit_full_frame_transforms_to_primary_event():
    parts, output_label = _build_smart_effect_video_filters(
        "v0",
        {
            "style": "smart_effect_punch_ai",
            "emphasis_overlays": [
                {"text": "", "start_time": 1.0, "end_time": 1.4},
                {"text": "重点", "start_time": 4.0, "end_time": 4.8},
                {"text": "再看这里", "start_time": 9.0, "end_time": 9.9},
            ],
        },
        expected_width=1920,
        expected_height=1080,
    )

    assert output_label == "vsmart2"
    assert sum("zoompan=" in part for part in parts) == 2
    assert sum("drawbox=" in part for part in parts) == 3


def test_overlay_only_editing_accents_normalizes_legacy_rhythm_style():
    accents = _build_overlay_only_editing_accents({"style": "smart_effect_rhythm"})

    assert accents["style"] == "smart_effect_commercial"


def test_sound_effect_filters_do_not_normalize_down_main_audio():
    filters, output_label = _build_sound_effect_filters(
        "0:a",
        {
            "sound_effects": [
                {"start_time": 1.0, "duration_sec": 0.08, "frequency": 960, "volume": 0.04},
                {"start_time": 2.5, "duration_sec": 0.08, "frequency": 840, "volume": 0.04},
            ]
        },
    )

    assert output_label == "amix1"
    assert sum("normalize=0" in part for part in filters) == 2


def test_video_encode_args_prefers_nvenc_when_available(monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    render_mod._nvenc_available.cache_clear()
    render_mod._nvidia_device_available.cache_clear()
    render_mod._ffmpeg_encoder_available.cache_clear()
    monkeypatch.setattr(render_mod, "_nvenc_available", lambda: True)
    monkeypatch.setattr(render_mod.get_settings(), "render_video_encoder", "auto")

    assert _resolve_video_encoder(prefer_hardware=True) == "h264_nvenc"
    args = _video_encode_args()
    assert args[:2] == ["-c:v", "h264_nvenc"]
    assert "-cq:v" in args


def test_video_encode_args_falls_back_to_cpu_when_nvenc_unavailable(monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    render_mod._nvenc_available.cache_clear()
    render_mod._nvidia_device_available.cache_clear()
    render_mod._ffmpeg_encoder_available.cache_clear()
    monkeypatch.setattr(render_mod, "_nvenc_available", lambda: False)
    monkeypatch.setattr(render_mod.get_settings(), "render_video_encoder", "auto")

    assert _resolve_video_encoder(prefer_hardware=True) == "libx264"
    args = _video_encode_args()
    assert args[:2] == ["-c:v", "libx264"]
    assert "-crf" in args


def test_resolve_delivery_resolution_supports_source_and_specified_modes():
    assert _resolve_delivery_resolution(
        expected_width=3840,
        expected_height=2160,
        delivery={"resolution_mode": "source", "resolution_preset": "1080p"},
    ) == (3840, 2160)
    assert _resolve_delivery_resolution(
        expected_width=3840,
        expected_height=2160,
        delivery={"resolution_mode": "specified", "resolution_preset": "1080p"},
    ) == (1920, 1080)
    assert _resolve_delivery_resolution(
        expected_width=1080,
        expected_height=1920,
        delivery={"resolution_mode": "specified", "resolution_preset": "1440p"},
    ) == (1440, 2560)


def test_materialize_long_filter_complex_args_uses_script_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    monkeypatch.setattr(render_mod, "tempfile", type("TmpModule", (), {"gettempdir": staticmethod(lambda: str(tmp_path))}))
    monkeypatch.setattr(render_mod.os, "name", "nt")
    monkeypatch.setattr(render_mod, "_WINDOWS_CMD_SOFT_LIMIT", 32)

    cmd = [
        "ffmpeg",
        "-i",
        "input.mp4",
        "-filter_complex",
        "[0:v]trim=start=0:end=10,setpts=PTS-STARTPTS[v0];" * 8,
        "-map",
        "[v0]",
        "out.mp4",
    ]

    rewritten, temp_files = _materialize_long_filter_complex_args(cmd)

    assert "-filter_complex_script" in rewritten
    assert "-filter_complex" not in rewritten
    assert len(temp_files) == 1
    assert temp_files[0].exists()
    assert temp_files[0].read_text(encoding="utf-8").startswith("[0:v]trim=")


def test_build_master_audio_filter_chain_applies_declipping_limiter_and_target_peak():
    chain = _build_master_audio_filter_chain(
        input_label="ain",
        voice_processing={"noise_reduction": True},
        loudness={"target_lufs": -16.0, "peak_limit": -2.0, "lra": 10.0},
        output_label="aout",
        allow_noise_reduction=True,
        include_declipping=True,
        include_async_resample=True,
    )

    assert chain.startswith("[ain]")
    assert "adeclip" in chain
    assert "anlmdn" in chain
    assert "loudnorm=I=-16.0:TP=-2.0:LRA=10.0:linear=true" in chain
    assert "alimiter=limit=" in chain
    assert chain.endswith("[aout]")


def test_stage_packaging_source_keeps_same_drive_inputs(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    staged = _stage_packaging_source(source, tmp_path)
    assert staged == source


@pytest.mark.asyncio
async def test_concat_prepared_bookends_prefers_stream_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    captured: dict[str, object] = {}

    class Result:
        returncode = 0
        stderr = ""

    async def fake_run_process(cmd: list[str], timeout: int):
        captured["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"video")
        return Result()

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 4.0)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)

    intro = tmp_path / "intro.mp4"
    body = tmp_path / "body.mp4"
    outro = tmp_path / "outro.mp4"
    for path in (intro, body, outro):
        path.write_bytes(b"video")

    output = tmp_path / "combined.mp4"
    copied = await _concat_prepared_bookends([intro, body, outro], output_path=output, debug_dir=None)

    assert copied is True
    assert captured["cmd"][0:7] == ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i"]
    assert captured["cmd"][-2:] == ["-c", "copy"] or captured["cmd"][-3:-1] == ["-c", "copy"]


@pytest.mark.asyncio
async def test_apply_music_and_watermark_ducks_music_under_voice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    captured: dict[str, object] = {}

    async def fake_run_process(cmd: list[str], timeout: int):
        captured["cmd"] = cmd

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    music = tmp_path / "music.mp3"
    music.write_bytes(b"audio")
    output = tmp_path / "out.mp4"

    await _apply_music_and_watermark(
        source,
        music_plan={
            "path": str(music),
            "loop_mode": "loop_single",
            "volume": 0.12,
            "enter_sec": 0.0,
        },
        watermark_plan=None,
        expected_width=736,
        expected_height=992,
        output_path=output,
        debug_dir=None,
    )

    filter_complex = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "highpass=f=120" in filter_complex
    assert "lowpass=f=6000" in filter_complex
    assert "sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350:makeup=1" in filter_complex
    assert "amix=inputs=2:duration=first:dropout_transition=2" in filter_complex


@pytest.mark.asyncio
async def test_render_video_applies_smart_effects_before_subtitle_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    commands: list[list[str]] = []

    class DummyResult:
        returncode = 0
        stderr = ""

    async def fake_run_process(cmd: list[str], timeout: int):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"video")
        return DummyResult()

    async def fake_detect_video_rotation(path: Path) -> int:
        return 0

    async def fake_normalize_rendered_output(*args, **kwargs):
        return None

    async def fake_resolve_subtitle_margin_with_avatar(**kwargs):
        return None

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 12.0)
    monkeypatch.setattr(
        render_mod,
        "_probe_video_stream",
        lambda path: {
            "width": 1920,
            "height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_raw": 0,
            "rotation_cw": 0,
        },
    )
    monkeypatch.setattr(render_mod, "_normalize_rendered_output", fake_normalize_rendered_output)
    monkeypatch.setattr(render_mod, "_write_debug_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_resolve_subtitle_margin_with_avatar", fake_resolve_subtitle_margin_with_avatar)

    from roughcut.media import rotation as rotation_mod

    monkeypatch.setattr(rotation_mod, "detect_video_rotation", fake_detect_video_rotation)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "out.mp4"

    await render_video(
        source_path=source,
        render_plan={
            "voice_processing": {},
            "loudness": {},
            "delivery": {"resolution_mode": "source"},
            "subtitles": {"style": "bold_yellow_outline", "motion_style": "motion_static"},
            "editing_accents": {
                "style": "smart_effect_punch",
                "transitions": {"enabled": False, "boundary_indexes": []},
                "emphasis_overlays": [{"text": "重点", "start_time": 1.0, "end_time": 1.6}],
                "sound_effects": [{"start_time": 1.0, "duration_sec": 0.08, "frequency": 960, "volume": 0.04}],
            },
            "avatar_commentary": None,
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
        },
        editorial_timeline={"segments": [{"type": "keep", "start": 0.0, "end": 4.0}]},
        output_path=output,
        subtitle_items=[{"start_time": 0.2, "end_time": 1.2, "text_final": "字幕"}],
        overlay_editing_accents={
            "style": "smart_effect_punch",
            "emphasis_overlays": [{"text": "重点", "start_time": 1.0, "end_time": 1.6}],
            "sound_effects": [{"start_time": 1.0, "duration_sec": 0.08, "frequency": 960, "volume": 0.04}],
        },
    )

    assert len(commands) == 2
    base_filter = commands[0][commands[0].index("-filter_complex") + 1]
    overlay_filter = commands[1][commands[1].index("-filter_complex") + 1]

    assert "zoompan=" in base_filter
    assert "subtitles='" not in base_filter
    assert "subtitles='" in overlay_filter
    assert "drawtext=" in overlay_filter


@pytest.mark.asyncio
async def test_render_video_overlay_copies_audio_when_no_audio_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    commands: list[list[str]] = []

    class DummyResult:
        returncode = 0
        stderr = ""

    async def fake_run_process(cmd: list[str], timeout: int):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"video")
        return DummyResult()

    async def fake_detect_video_rotation(path: Path) -> int:
        return 0

    async def fake_normalize_rendered_output(*args, **kwargs):
        return None

    async def fake_resolve_subtitle_margin_with_avatar(**kwargs):
        return None

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 12.0)
    monkeypatch.setattr(
        render_mod,
        "_probe_video_stream",
        lambda path: {
            "width": 1920,
            "height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_raw": 0,
            "rotation_cw": 0,
        },
    )
    monkeypatch.setattr(render_mod, "_normalize_rendered_output", fake_normalize_rendered_output)
    monkeypatch.setattr(render_mod, "_write_debug_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_resolve_subtitle_margin_with_avatar", fake_resolve_subtitle_margin_with_avatar)
    monkeypatch.setattr(render_mod, "_nvenc_available", lambda: False)

    from roughcut.media import rotation as rotation_mod

    monkeypatch.setattr(rotation_mod, "detect_video_rotation", fake_detect_video_rotation)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "out.mp4"

    await render_video(
        source_path=source,
        render_plan={
            "voice_processing": {},
            "loudness": {},
            "delivery": {"resolution_mode": "source"},
            "subtitles": {"style": "bold_yellow_outline", "motion_style": "motion_static"},
            "editing_accents": {
                "style": "smart_effect_rhythm",
                "transitions": {"enabled": False, "boundary_indexes": []},
                "emphasis_overlays": [],
                "sound_effects": [],
            },
            "avatar_commentary": None,
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
        },
        editorial_timeline={"segments": [{"type": "keep", "start": 0.0, "end": 4.0}]},
        output_path=output,
        subtitle_items=[{"start_time": 0.2, "end_time": 1.2, "text_final": "字幕"}],
        overlay_editing_accents={"style": "smart_effect_rhythm", "emphasis_overlays": [], "sound_effects": []},
    )

    assert len(commands) == 2
    overlay_cmd = commands[1]
    assert overlay_cmd[overlay_cmd.index("-c:a") + 1] == "copy"
