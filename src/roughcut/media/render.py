from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from roughcut.config import get_settings


logger = logging.getLogger(__name__)
_WINDOWS_CMD_SOFT_LIMIT = 30000

_EXPORT_RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2160p": (3840, 2160),
}

_TRANSPOSE_MAP = {
    90: ",transpose=1",
    180: ",hflip,vflip",
    270: ",transpose=2",
}

_DEFAULT_TARGET_LUFS = -16.0
_DEFAULT_PEAK_LIMIT_DB = -2.0
_DEFAULT_LRA = 10.0


def _resolve_ffmpeg_timeout(
    *,
    source_duration_sec: float | None = None,
    multiplier: float = 1.6,
    buffer_sec: int = 300,
    minimum_timeout: int | None = None,
) -> int:
    settings = get_settings()
    base_timeout = int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600)
    minimum = max(base_timeout, int(minimum_timeout or 0))
    if not source_duration_sec or source_duration_sec <= 0:
        return minimum
    adaptive_timeout = int(source_duration_sec * multiplier + buffer_sec)
    return max(minimum, adaptive_timeout)


async def render_video(
    source_path: Path,
    render_plan: dict,
    editorial_timeline: dict,
    output_path: Path,
    subtitle_items: list[dict] | None = None,
    overlay_editing_accents: dict[str, Any] | None = None,
    progress_callback: Callable[[float], None] | None = None,
    debug_dir: Path | None = None,
) -> Path:
    """
    Render video according to editorial_timeline and render_plan.

    Rotation handling:
      1. Read the raw source stream geometry for the downloaded file.
      2. Ask the vision model how much clockwise rotation is actually needed.
      3. Render with -noautorotate and an explicit transpose filter.
      4. Verify the rendered output is physically normalized and retry a more
         explicit normalization pass if stale rotation metadata survived.
    """
    del progress_callback  # Progress callbacks are not wired up yet.
    settings = get_settings()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
    try:
        source_duration = _probe_duration(source_path)
    except Exception:
        source_duration = 0.0

    packaging_enabled = any(render_plan.get(key) for key in ("intro", "outro", "insert", "watermark", "music"))
    base_output_path = output_path if not packaging_enabled else output_path.with_name(f"{output_path.stem}.base{output_path.suffix}")

    keep_segments = [
        s for s in editorial_timeline.get("segments", [])
        if s.get("type") == "keep"
    ]
    if not keep_segments:
        raise ValueError("No keep segments in editorial timeline")

    source_info = _probe_video_stream(source_path)
    _write_debug_json(debug_dir, "source.ffprobe.json", source_info)

    from roughcut.media.rotation import detect_video_rotation

    rotation_cw = await detect_video_rotation(source_path)
    transpose_suffix = _TRANSPOSE_MAP.get(rotation_cw, "")

    raw_w = source_info["width"]
    raw_h = source_info["height"]
    if rotation_cw in (90, 270):
        expected_w, expected_h = raw_h, raw_w
    else:
        expected_w, expected_h = raw_w, raw_h
    render_w, render_h = _resolve_delivery_resolution(
        expected_width=expected_w,
        expected_height=expected_h,
        delivery=render_plan.get("delivery") or {},
    )

    _write_debug_json(
        debug_dir,
        "orientation.expected.json",
        {
            "source_path": str(source_path),
            "source_rotation_raw": source_info["rotation_raw"],
            "source_rotation_cw": source_info["rotation_cw"],
            "vision_rotation_cw": rotation_cw,
            "expected_width": expected_w,
            "expected_height": expected_h,
        },
    )

    filter_parts: list[str] = []
    editing_accents = render_plan.get("editing_accents") or {}
    segment_filters, video_label, audio_label = _build_segment_filter_chain(
        keep_segments,
        transpose_suffix=transpose_suffix,
        editing_accents=editing_accents,
    )
    filter_parts.extend(segment_filters)

    audio_filter = _build_master_audio_filter_chain(
        input_label=audio_label,
        voice_processing=render_plan.get("voice_processing") or {},
        loudness=render_plan.get("loudness") or {},
        output_label="afinal",
        allow_noise_reduction=True,
        include_declipping=True,
        include_async_resample=True,
    )
    filter_parts.append(audio_filter)
    video_map = f"[{video_label}]"

    if editing_accents.get("emphasis_overlays") and _should_apply_smart_effect_video_transforms(render_plan.get("avatar_commentary") or {}):
        smart_effect_filters, video_label = _build_smart_effect_video_filters(
            video_label,
            editing_accents,
            expected_width=render_w,
            expected_height=render_h,
        )
        filter_parts.extend(smart_effect_filters)
        video_map = f"[{video_label}]"

    if (render_w, render_h) != (expected_w, expected_h):
        filter_parts.append(
            f"[{video_label}]scale={render_w}:{render_h}:force_original_aspect_ratio=decrease,"
            f"pad={render_w}:{render_h}:(ow-iw)/2:(oh-ih)/2:color=black[vscaled]"
        )
        video_label = "vscaled"
        video_map = f"[{video_label}]"

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        "-noautorotate",
        "-i",
        str(source_path),
        "-filter_complex",
        filter_complex,
        "-map",
        video_map,
        "-map",
        "[afinal]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(base_output_path),
    ]
    _write_debug_text(debug_dir, "render.ffmpeg.txt", _format_command(cmd))

    result = await _run_process(
        cmd,
        timeout=_resolve_ffmpeg_timeout(
            source_duration_sec=source_duration,
            multiplier=1.5,
            buffer_sec=240,
        ),
    )
    _write_process_debug(debug_dir, "render", result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg render failed: {result.stderr[-2000:]}")

    await _normalize_rendered_output(
        base_output_path,
        expected_width=render_w,
        expected_height=render_h,
        debug_dir=debug_dir,
    )
    current_output = base_output_path
    if packaging_enabled:
        packaged = await _apply_packaging_plan(
            base_output_path,
            render_plan=render_plan,
            output_path=output_path,
            expected_width=render_w,
            expected_height=render_h,
            debug_dir=debug_dir,
        )
        await _normalize_rendered_output(
            packaged,
            expected_width=render_w,
            expected_height=render_h,
            debug_dir=debug_dir,
        )
        current_output = packaged
    elif base_output_path != output_path:
        _finalize_output_file(base_output_path, output_path)
        current_output = output_path

    overlay_plan = _build_overlay_only_editing_accents(
        overlay_editing_accents if isinstance(overlay_editing_accents, dict) else editing_accents
    )
    if subtitle_items or overlay_plan.get("emphasis_overlays") or overlay_plan.get("sound_effects"):
        overlay_output_path = output_path
        if current_output == output_path:
            overlay_output_path = output_path.with_name(f"{output_path.stem}.overlay{output_path.suffix}")
        await _apply_timed_overlays_to_video(
            current_output,
            output_path=overlay_output_path,
            render_plan=render_plan,
            subtitle_items=subtitle_items,
            overlay_editing_accents=overlay_plan,
            debug_dir=debug_dir,
        )
        if overlay_output_path != output_path:
            _finalize_output_file(overlay_output_path, output_path)
        current_output = output_path

    return current_output


def _build_segment_filter_chain(
    keep_segments: list[dict[str, Any]],
    *,
    transpose_suffix: str,
    editing_accents: dict[str, Any],
) -> tuple[list[str], str, str]:
    parts: list[str] = []
    transition_map = _resolve_transition_map(
        keep_segments,
        editing_accents.get("transitions") or {},
    )
    needs_constant_fps = bool(transition_map)
    video_timing_suffix = f"{transpose_suffix},fps=30000/1001,settb=AVTB" if needs_constant_fps else transpose_suffix
    segment_durations: list[float] = []
    for index, segment in enumerate(keep_segments):
        start = float(segment["start"])
        end = float(segment["end"])
        duration = max(0.0, end - start)
        segment_durations.append(duration)
        parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS{video_timing_suffix}[v{index}]")
        parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]")

    current_video = "v0"
    current_audio = "a0"
    current_duration = segment_durations[0]

    for index in range(1, len(keep_segments)):
        next_video = f"v{index}"
        next_audio = f"a{index}"
        next_duration = segment_durations[index]
        boundary_index = index - 1
        output_video = f"vchain{index}"
        output_audio = f"achain{index}"
        transition_duration = transition_map.get(boundary_index)
        if transition_duration is not None:
            offset = max(0.0, current_duration - transition_duration)
            transition_name = str((editing_accents.get("transitions") or {}).get("transition") or "fade").strip() or "fade"
            parts.append(
                f"[{current_video}][{next_video}]xfade=transition={transition_name}:duration={transition_duration}:offset={offset}[{output_video}]"
            )
            parts.append(
                f"[{current_audio}][{next_audio}]acrossfade=d={transition_duration}:c1=tri:c2=tri[{output_audio}]"
            )
            current_duration = current_duration + next_duration - transition_duration
        else:
            parts.append(
                f"[{current_video}][{current_audio}][{next_video}][{next_audio}]concat=n=2:v=1:a=1[{output_video}][{output_audio}]"
            )
            current_duration += next_duration
        current_video = output_video
        current_audio = output_audio

    parts.append(f"[{current_video}]sidedata=mode=delete:type=DISPLAYMATRIX[vout]")
    return parts, "vout", current_audio


def _resolve_transition_map(
    keep_segments: list[dict[str, Any]],
    transitions: dict[str, Any],
) -> dict[int, float]:
    if not transitions.get("enabled"):
        return {}
    raw_duration = float(transitions.get("duration_sec") or 0.12)
    requested_indexes = [
        int(index)
        for index in transitions.get("boundary_indexes") or []
        if 0 <= int(index) < len(keep_segments) - 1
    ]
    resolved: dict[int, float] = {}
    for index in requested_indexes:
        current = keep_segments[index]
        following = keep_segments[index + 1]
        current_duration = float(current["end"]) - float(current["start"])
        next_duration = float(following["end"]) - float(following["start"])
        transition_duration = min(max(raw_duration, 0.08), current_duration / 4, next_duration / 4, 0.18)
        if transition_duration < 0.08:
            continue
        resolved[index] = round(transition_duration, 3)
    return resolved


def _build_sound_effect_filters(
    audio_label: str,
    editing_accents: dict[str, Any],
) -> tuple[list[str], str]:
    parts: list[str] = []
    current_audio = audio_label
    for index, event in enumerate(editing_accents.get("sound_effects") or []):
        start_time = max(0.0, float(event.get("start_time") or 0.0))
        duration = max(0.05, min(float(event.get("duration_sec") or 0.08), 0.18))
        frequency = int(event.get("frequency") or 960)
        volume = max(0.01, min(float(event.get("volume") or 0.045), 0.08))
        delay_ms = int(start_time * 1000)
        fx_label = f"fx{index}"
        mixed_label = f"amix{index}"
        fade_out_start = max(duration - 0.04, 0.0)
        parts.append(
            f"sine=frequency={frequency}:sample_rate=48000:duration={duration},"
            f"volume={volume},afade=t=out:st={fade_out_start}:d=0.04,"
            f"adelay={delay_ms}|{delay_ms}[{fx_label}]"
        )
        parts.append(f"[{current_audio}][{fx_label}]amix=inputs=2:duration=first:dropout_transition=0[{mixed_label}]")
        current_audio = mixed_label
    return parts, current_audio


def _db_to_linear_gain(db_value: float) -> float:
    return 10 ** (db_value / 20.0)


def _build_master_audio_filter_chain(
    *,
    input_label: str,
    voice_processing: dict[str, Any],
    loudness: dict[str, Any],
    output_label: str,
    allow_noise_reduction: bool,
    include_declipping: bool,
    include_async_resample: bool,
) -> str:
    target_lufs = float(loudness.get("target_lufs") or _DEFAULT_TARGET_LUFS)
    peak_limit_db = float(loudness.get("peak_limit") or _DEFAULT_PEAK_LIMIT_DB)
    lra = float(loudness.get("lra") or _DEFAULT_LRA)
    limiter_linear = max(0.05, min(0.99, _db_to_linear_gain(peak_limit_db)))

    filters: list[str] = []
    if include_async_resample:
        filters.append("aresample=async=1:first_pts=0")
    if include_declipping:
        filters.append("adeclip")
    if allow_noise_reduction and bool(voice_processing.get("noise_reduction")):
        filters.append("anlmdn")
    filters.append(f"loudnorm=I={target_lufs}:TP={peak_limit_db}:LRA={lra}:linear=true")
    filters.append(f"alimiter=limit={limiter_linear:.6f}:level=disabled")
    return f"[{input_label}]" + ",".join(filters) + f"[{output_label}]"


def _build_emphasis_overlay_filters(
    video_label: str,
    editing_accents: dict[str, Any],
) -> tuple[list[str], str]:
    parts: list[str] = []
    current_video = video_label
    font_name = _escape_drawtext_value(get_settings().subtitle_font)
    style_tokens = _resolve_effect_overlay_tokens(str(editing_accents.get("style") or "smart_effect_rhythm"))
    for index, overlay in enumerate(editing_accents.get("emphasis_overlays") or []):
        text = _escape_drawtext_value(str(overlay.get("text") or ""))
        if not text:
            continue
        start_time = max(0.0, float(overlay.get("start_time") or 0.0))
        end_time = max(start_time + 0.2, float(overlay.get("end_time") or start_time + 1.0))
        fade_duration = min(0.12, max((end_time - start_time) / 3, 0.06))
        alpha_expr = (
            f"if(lt(t\\,{start_time})\\,0\\,"
            f"if(lt(t\\,{start_time + fade_duration})\\,(t-{start_time})/{fade_duration}*0.96\\,"
            f"if(lt(t\\,{end_time - fade_duration})\\,0.96\\,"
            f"if(lt(t\\,{end_time})\\,({end_time}-t)/{fade_duration}*0.96\\,0))))"
        )
        output_label = f"vfx{index}"
        parts.append(
            f"[{current_video}]drawtext="
            f"font='{font_name}':"
            f"text='{text}':"
            f"fontsize={style_tokens['fontsize']}:"
            f"fontcolor={style_tokens['fontcolor']}:"
            f"alpha='{alpha_expr}':"
            f"box=1:boxcolor={style_tokens['boxcolor']}:boxborderw={style_tokens['boxborderw']}:"
            f"borderw={style_tokens['borderw']}:bordercolor={style_tokens['bordercolor']}:"
            f"x=(w-text_w)/2:y=h*{style_tokens['y_ratio']}"
            f"[{output_label}]"
        )
        current_video = output_label
    return parts, current_video


def _build_smart_effect_video_filters(
    video_label: str,
    editing_accents: dict[str, Any],
    *,
    expected_width: int,
    expected_height: int,
) -> tuple[list[str], str]:
    overlays = list(editing_accents.get("emphasis_overlays") or [])
    if not overlays:
        return [], video_label

    style = str(editing_accents.get("style") or "smart_effect_rhythm")
    tokens = _resolve_smart_effect_video_tokens(style)
    zoom_size = f"{expected_width}x{expected_height}"
    parts: list[str] = []
    current_video = video_label

    for index, overlay in enumerate(overlays):
        start_time = max(0.0, float(overlay.get("start_time") or 0.0))
        end_time = max(start_time + 0.24, float(overlay.get("end_time") or start_time + 1.0))
        attack_end = min(end_time, start_time + max(0.08, (end_time - start_time) * 0.38))
        enable_expr = f"between(t\\,{start_time}\\,{end_time})"
        zoom_expr = (
            f"if(lte(in_time\\,{start_time})\\,1\\,"
            f"if(lte(in_time\\,{attack_end})\\,1+((in_time-{start_time})/{max(attack_end - start_time, 0.01)})*{tokens['zoom_peak']}\\,"
            f"1+(({end_time}-in_time)/{max(end_time - attack_end, 0.01)})*{tokens['zoom_decay']}))"
        )
        output_label = f"vsmart{index}"
        parts.append(
            f"[{current_video}]scale=iw*{tokens['pre_scale']}:ih*{tokens['pre_scale']},"
            f"crop=w=iw/{tokens['pre_scale']}:h=ih/{tokens['pre_scale']}:"
            f"x='(iw-iw/{tokens['pre_scale']})/2':y='(ih-ih/{tokens['pre_scale']})/2',"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={zoom_size}:fps=30000/1001,"
            f"eq=contrast={tokens['contrast']}:saturation={tokens['saturation']}:brightness={tokens['brightness']},"
            f"unsharp={tokens['unsharp']},"
            f"drawbox=x=0:y=0:w=iw:h=ih:color={tokens['flash_color']}:t=fill:enable='{enable_expr}':replace=0"
            f"[{output_label}]"
        )
        current_video = output_label
    return parts, current_video


def _build_overlay_only_editing_accents(editing_accents: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(editing_accents or {})
    return {
        "style": str(base.get("style") or "smart_effect_rhythm"),
        "emphasis_overlays": [dict(item) for item in base.get("emphasis_overlays") or []],
        "sound_effects": [dict(item) for item in base.get("sound_effects") or []],
    }


async def _apply_timed_overlays_to_video(
    source_path: Path,
    *,
    output_path: Path,
    render_plan: dict[str, Any],
    subtitle_items: list[dict] | None,
    overlay_editing_accents: dict[str, Any] | None,
    debug_dir: Path | None,
) -> Path:
    from roughcut.media.subtitles import escape_path_for_ffmpeg_filter, write_ass_file

    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source_info = _probe_video_stream(source_path)
    render_w = int(source_info.get("display_width") or source_info.get("width") or 0)
    render_h = int(source_info.get("display_height") or source_info.get("height") or 0)
    overlay_plan = _build_overlay_only_editing_accents(overlay_editing_accents)

    filter_parts: list[str] = []
    video_label = "0:v"
    audio_label = "0:a"
    video_map = "0:v"
    audio_map = "0:a"

    if subtitle_items and render_plan.get("subtitles"):
        ass_path = output_path.parent / f"{output_path.stem}.subtitle.ass"
        write_ass_file(
            subtitle_items,
            ass_path,
            style_name=str((render_plan.get("subtitles") or {}).get("style") or "bold_yellow_outline"),
            font_name=settings.subtitle_font,
            font_size=settings.subtitle_font_size,
            text_color_rgb=settings.subtitle_color,
            outline_color_rgb=settings.subtitle_outline_color,
            outline_width=settings.subtitle_outline_width,
            margin_v_override=await _resolve_subtitle_margin_with_avatar(
                expected_width=render_w,
                expected_height=render_h,
                avatar_plan=render_plan.get("avatar_commentary") or {},
            ),
            motion_style=str((render_plan.get("subtitles") or {}).get("motion_style") or "motion_static"),
            play_res_x=render_w,
            play_res_y=render_h,
        )
        escaped = escape_path_for_ffmpeg_filter(ass_path)
        filter_parts.append(f"[{video_label}]subtitles='{escaped}'[vsub]")
        video_label = "vsub"
        video_map = f"[{video_label}]"

    if overlay_plan.get("emphasis_overlays"):
        overlay_filters, video_label = _build_emphasis_overlay_filters(video_label, overlay_plan)
        filter_parts.extend(overlay_filters)
        video_map = f"[{video_label}]"

    if overlay_plan.get("sound_effects"):
        sfx_filters, audio_label = _build_sound_effect_filters(audio_label, overlay_plan)
        filter_parts.extend(sfx_filters)
        audio_map = f"[{audio_label}]"

    if not filter_parts:
        if source_path != output_path:
            _finalize_output_file(source_path, output_path)
        return output_path

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        video_map,
        "-map",
        audio_map,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    _write_debug_text(debug_dir, "render.overlays.ffmpeg.txt", _format_command(cmd))
    result = await _run_process(
        cmd,
        timeout=_resolve_ffmpeg_timeout(
            source_duration_sec=_probe_duration(source_path),
            multiplier=1.2,
            buffer_sec=180,
            minimum_timeout=300,
        ),
    )
    _write_process_debug(debug_dir, "render_overlays", result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg timed overlay render failed: {result.stderr[-2000:]}")
    return output_path


def _resolve_effect_overlay_tokens(style: str) -> dict[str, Any]:
    mapping: dict[str, dict[str, Any]] = {
        "smart_effect_rhythm": {
            "fontsize": 72,
            "fontcolor": "white",
            "boxcolor": "black@0.45",
            "boxborderw": 18,
            "borderw": 2,
            "bordercolor": "black@0.25",
            "y_ratio": 0.18,
        },
        "smart_effect_punch": {
            "fontsize": 86,
            "fontcolor": "white",
            "boxcolor": "0x3a0505@0.58",
            "boxborderw": 24,
            "borderw": 3,
            "bordercolor": "0xff874d@0.52",
            "y_ratio": 0.16,
        },
        "smart_effect_glitch": {
            "fontsize": 78,
            "fontcolor": "0xeef2ff",
            "boxcolor": "0x11162f@0.6",
            "boxborderw": 20,
            "borderw": 2,
            "bordercolor": "0x6f7fff@0.48",
            "y_ratio": 0.17,
        },
        "smart_effect_cinematic": {
            "fontsize": 68,
            "fontcolor": "0xfff4e8",
            "boxcolor": "0x120d08@0.4",
            "boxborderw": 16,
            "borderw": 1,
            "bordercolor": "0xe2b471@0.34",
            "y_ratio": 0.2,
        },
        "smart_effect_minimal": {
            "fontsize": 62,
            "fontcolor": "white",
            "boxcolor": "black@0.28",
            "boxborderw": 12,
            "borderw": 1,
            "bordercolor": "white@0.12",
            "y_ratio": 0.2,
        },
    }
    return mapping.get(style, mapping["smart_effect_rhythm"])


def _resolve_smart_effect_video_tokens(style: str) -> dict[str, Any]:
    base = {
        "pre_scale": 1.18,
        "zoom_peak": 0.08,
        "zoom_decay": 0.04,
        "contrast": 1.04,
        "saturation": 1.08,
        "brightness": 0.015,
        "unsharp": "5:5:0.8:3:3:0.0",
        "flash_color": "white@0.08",
    }
    mapping: dict[str, dict[str, Any]] = {
        "smart_effect_rhythm": {
            **base,
            "pre_scale": 1.14,
            "zoom_peak": 0.05,
            "zoom_decay": 0.025,
            "contrast": 1.025,
            "saturation": 1.04,
            "brightness": 0.01,
            "flash_color": "white@0.06",
        },
        "smart_effect_punch": {
            **base,
            "pre_scale": 1.22,
            "zoom_peak": 0.12,
            "zoom_decay": 0.08,
            "contrast": 1.08,
            "saturation": 1.14,
            "brightness": 0.024,
            "unsharp": "5:5:1.1:3:3:0.0",
            "flash_color": "white@0.16",
        },
        "smart_effect_glitch": {
            **base,
            "pre_scale": 1.17,
            "zoom_peak": 0.09,
            "zoom_decay": 0.05,
            "contrast": 1.06,
            "saturation": 1.18,
            "brightness": 0.008,
            "flash_color": "0x8d7bff@0.12",
        },
        "smart_effect_cinematic": {
            **base,
            "pre_scale": 1.1,
            "zoom_peak": 0.04,
            "zoom_decay": 0.02,
            "contrast": 1.02,
            "saturation": 1.02,
            "brightness": 0.004,
            "unsharp": "5:5:0.45:3:3:0.0",
            "flash_color": "0xf2c07a@0.035",
        },
        "smart_effect_minimal": {
            **base,
            "pre_scale": 1.08,
            "zoom_peak": 0.02,
            "zoom_decay": 0.012,
            "contrast": 1.01,
            "saturation": 1.01,
            "brightness": 0.0,
            "unsharp": "5:5:0.25:3:3:0.0",
            "flash_color": "white@0.02",
        },
    }
    return mapping.get(style, mapping["smart_effect_rhythm"])


def _should_apply_smart_effect_video_transforms(avatar_plan: dict[str, Any]) -> bool:
    integration_mode = str(avatar_plan.get("integration_mode") or "").strip().lower()
    # Once a picture-in-picture avatar has been merged into the plain render, any
    # full-frame crop/zoom will also crop the avatar and subtitle safe area.
    return integration_mode != "picture_in_picture"


def _resolve_delivery_resolution(
    *,
    expected_width: int,
    expected_height: int,
    delivery: dict[str, Any],
) -> tuple[int, int]:
    mode = str(delivery.get("resolution_mode") or "source").strip().lower()
    if mode != "specified":
        return expected_width, expected_height

    preset = str(delivery.get("resolution_preset") or "1080p").strip().lower()
    target = _EXPORT_RESOLUTION_PRESETS.get(preset)
    if target is None:
        return expected_width, expected_height

    landscape_w, landscape_h = target
    if expected_height > expected_width:
        return landscape_h, landscape_w
    return landscape_w, landscape_h


def _escape_drawtext_value(value: str) -> str:
    escaped = value.replace("\\", r"\\")
    escaped = escaped.replace(":", r"\:")
    escaped = escaped.replace("'", r"\'")
    escaped = escaped.replace("%", r"\%")
    escaped = escaped.replace(",", r"\,")
    return escaped


async def _resolve_subtitle_margin_with_avatar(
    *,
    expected_width: int,
    expected_height: int,
    avatar_plan: dict[str, Any],
) -> int | None:
    if str(avatar_plan.get("integration_mode") or "") != "picture_in_picture":
        return None
    position = str(avatar_plan.get("overlay_position") or "bottom_right").strip() or "bottom_right"
    if not position.startswith("bottom_"):
        return None

    scale = max(0.16, min(0.42, float(avatar_plan.get("overlay_scale") or 0.28)))
    safe_margin = max(0.02, min(0.2, float(avatar_plan.get("safe_margin") or 0.08)))
    border_width = max(0, int(avatar_plan.get("overlay_border_width") or 0))
    presenter_id = str(avatar_plan.get("presenter_id") or "").strip()

    aspect_ratio = 0.75
    if presenter_id:
        try:
            presenter_info = _probe_video_stream(Path(presenter_id))
            if presenter_info["width"] > 0 and presenter_info["height"] > 0:
                aspect_ratio = presenter_info["height"] / presenter_info["width"]
        except Exception:
            pass

    overlay_width = max(180, int(round(expected_width * scale)))
    overlay_height = int(round(overlay_width * aspect_ratio))
    margin_px = max(18, int(round(min(expected_width, expected_height) * safe_margin)))

    face_protect_ratio = 0.58
    chin_overlap_ratio = 0.18
    protected_height = int(round(overlay_height * face_protect_ratio))
    allowed_overlap = int(round(overlay_height * chin_overlap_ratio))
    clearance = max(
        48,
        protected_height - allowed_overlap + margin_px + border_width * 2 + 20,
    )
    return min(expected_height - 48, clearance)


async def _apply_packaging_plan(
    source_path: Path,
    *,
    render_plan: dict,
    output_path: Path,
    expected_width: int,
    expected_height: int,
    debug_dir: Path | None,
) -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        current_path = _stage_packaging_source(source_path, tmp)
        insert_plan = render_plan.get("insert")
        if insert_plan:
            current_path = await _apply_insert_clip(
                current_path,
                insert_plan=insert_plan,
                expected_width=expected_width,
                expected_height=expected_height,
                output_path=tmp / "inserted.mp4",
                debug_dir=debug_dir,
            )
        if render_plan.get("intro") or render_plan.get("outro"):
            current_path = await _apply_intro_outro(
                current_path,
                intro_plan=render_plan.get("intro"),
                outro_plan=render_plan.get("outro"),
                expected_width=expected_width,
                expected_height=expected_height,
                output_path=tmp / "with_bookends.mp4",
                debug_dir=debug_dir,
            )
        if render_plan.get("music") or render_plan.get("watermark"):
            current_path = await _apply_music_and_watermark(
                current_path,
                music_plan=render_plan.get("music"),
                watermark_plan=render_plan.get("watermark"),
                expected_width=expected_width,
                expected_height=expected_height,
                output_path=tmp / "packaged.mp4",
                debug_dir=debug_dir,
            )
        if current_path != output_path:
            _finalize_output_file(current_path, output_path)
    return output_path


def _stage_packaging_source(source_path: Path, temp_root: Path) -> Path:
    source_drive = source_path.drive.lower()
    temp_drive = temp_root.drive.lower()
    if source_drive and temp_drive and source_drive != temp_drive:
        staged = temp_root / f"packaging_source{source_path.suffix}"
        shutil.copy2(source_path, staged)
        return staged
    return source_path


async def _apply_insert_clip(
    source_path: Path,
    *,
    insert_plan: dict,
    expected_width: int,
    expected_height: int,
    output_path: Path,
    debug_dir: Path | None,
) -> Path:
    insert_after_sec = float(insert_plan.get("insert_after_sec", 0.0) or 0.0)
    source_duration = _probe_duration(source_path)
    if source_duration <= 0.0:
        return source_path
    insert_after_sec = max(0.0, min(insert_after_sec, max(0.0, source_duration - 0.1)))

    prepared_insert = output_path.with_name("insert_asset.prepared.mp4")
    await _prepare_packaging_clip(
        Path(insert_plan["path"]),
        prepared_insert,
        expected_width=expected_width,
        expected_height=expected_height,
    )

    filter_complex = (
        "[0:v]split[vpre][vpost];"
        "[0:a]asplit[apre][apost];"
        f"[vpre]trim=start=0:end={insert_after_sec},setpts=PTS-STARTPTS[v0];"
        f"[apre]atrim=start=0:end={insert_after_sec},asetpts=PTS-STARTPTS[a0];"
        f"[vpost]trim=start={insert_after_sec},setpts=PTS-STARTPTS[v2];"
        f"[apost]atrim=start={insert_after_sec},asetpts=PTS-STARTPTS[a2];"
        "[1:v]setpts=PTS-STARTPTS[v1];"
        "[1:a]asetpts=PTS-STARTPTS[a1];"
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vout][aout]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-i",
        str(prepared_insert),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    _write_debug_text(debug_dir, "packaging.insert.ffmpeg.txt", _format_command(cmd))
    result = await _run_process(
        cmd,
        timeout=_resolve_ffmpeg_timeout(
            source_duration_sec=source_duration,
            multiplier=1.4,
            buffer_sec=180,
        ),
    )
    _write_process_debug(debug_dir, "packaging.insert", result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg insert packaging failed: {result.stderr[-2000:]}")
    return output_path


async def _apply_intro_outro(
    source_path: Path,
    *,
    intro_plan: dict | None,
    outro_plan: dict | None,
    expected_width: int,
    expected_height: int,
    output_path: Path,
    debug_dir: Path | None,
) -> Path:
    prepared_paths: list[Path] = []
    if intro_plan:
        intro_prepared = output_path.with_name("intro_asset.prepared.mp4")
        await _prepare_packaging_clip(
            Path(intro_plan["path"]),
            intro_prepared,
            expected_width=expected_width,
            expected_height=expected_height,
        )
        prepared_paths.append(intro_prepared)

    prepared_paths.append(source_path)

    if outro_plan:
        outro_prepared = output_path.with_name("outro_asset.prepared.mp4")
        await _prepare_packaging_clip(
            Path(outro_plan["path"]),
            outro_prepared,
            expected_width=expected_width,
            expected_height=expected_height,
        )
        prepared_paths.append(outro_prepared)

    if len(prepared_paths) == 1:
        return source_path

    cmd = ["ffmpeg", "-y"]
    for path in prepared_paths:
        cmd.extend(["-i", str(path)])

    concat_inputs = "".join(f"[{index}:v][{index}:a]" for index in range(len(prepared_paths)))
    cmd.extend(
        [
            "-filter_complex",
            f"{concat_inputs}concat=n={len(prepared_paths)}:v=1:a=1[vout][aout]",
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ]
    )
    _write_debug_text(debug_dir, "packaging.bookends.ffmpeg.txt", _format_command(cmd))
    result = await _run_process(
        cmd,
        timeout=_resolve_ffmpeg_timeout(
            source_duration_sec=_probe_duration(source_path),
            multiplier=1.4,
            buffer_sec=180,
        ),
    )
    _write_process_debug(debug_dir, "packaging.bookends", result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg intro/outro packaging failed: {result.stderr[-2000:]}")
    return output_path


async def _apply_music_and_watermark(
    source_path: Path,
    *,
    music_plan: dict | None,
    watermark_plan: dict | None,
    expected_width: int,
    expected_height: int,
    output_path: Path,
    debug_dir: Path | None,
) -> Path:
    if not music_plan and not watermark_plan:
        return source_path
    try:
        source_duration = _probe_duration(source_path)
    except Exception:
        source_duration = 0.0

    cmd = ["ffmpeg", "-y", "-i", str(source_path)]
    filter_parts: list[str] = []
    video_map = "0:v:0"
    audio_map = "0:a:0"
    next_input_index = 1

    if music_plan:
        music_input_path = Path(music_plan["path"])
        if music_plan.get("loop_mode") == "loop_all":
            music_input_path = await _prepare_multi_track_music_loop(
                candidate_paths=[Path(path) for path in music_plan.get("candidate_paths") or [music_plan["path"]]],
                output_path=output_path.with_name("music.loop_all.m4a"),
                debug_dir=debug_dir,
            )
        if music_plan.get("loop_mode") in {"loop_single", "loop_all"}:
            cmd.extend(["-stream_loop", "-1"])
        cmd.extend(["-i", str(music_input_path)])
        volume = float(music_plan.get("volume", 0.12) or 0.12)
        enter_sec = max(0.0, float(music_plan.get("enter_sec", 0.0) or 0.0))
        if enter_sec > 0:
            delay_ms = int(round(enter_sec * 1000))
            filter_parts.append(
                f"[{next_input_index}:a]volume={volume},highpass=f=120,lowpass=f=6000,adelay={delay_ms}|{delay_ms}[bgm_pre]"
            )
        else:
            filter_parts.append(f"[{next_input_index}:a]volume={volume},highpass=f=120,lowpass=f=6000[bgm_pre]")
        filter_parts.append(
            "[bgm_pre][0:a]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350:makeup=1[bgm]"
        )
        filter_parts.append(f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[amixed]")
        filter_parts.append(
            _build_master_audio_filter_chain(
                input_label="amixed",
                voice_processing={"noise_reduction": False},
                loudness={"target_lufs": _DEFAULT_TARGET_LUFS, "peak_limit": _DEFAULT_PEAK_LIMIT_DB, "lra": _DEFAULT_LRA},
                output_label="aout",
                allow_noise_reduction=False,
                include_declipping=False,
                include_async_resample=False,
            )
        )
        audio_map = "[aout]"
        next_input_index += 1

    if watermark_plan:
        cmd.extend(["-i", str(watermark_plan["path"])])
        opacity = float(watermark_plan.get("opacity", 0.82) or 0.82)
        scale = float(watermark_plan.get("scale", 0.16) or 0.16)
        overlay_x, overlay_y = _watermark_overlay_position(str(watermark_plan.get("position") or "top_right"))
        watermark_width = max(1, int(round(expected_width * scale)))
        watermark_filters = [f"[{next_input_index}:v]scale={watermark_width}:-1", "format=rgba"]
        if not bool(watermark_plan.get("watermark_preprocessed")):
            # Uploaded logo assets are often flattened onto white backgrounds; key near-white tones out at render time.
            watermark_filters.append("colorkey=0xF8F8F8:0.20:0.08")
        watermark_filters.append(f"colorchannelmixer=aa={opacity}[wmfinal]")
        filter_parts.append(",".join(watermark_filters))
        filter_parts.append(f"[0:v][wmfinal]overlay=x={overlay_x}:y={overlay_y}:format=auto[vout]")
        video_map = "[vout]"

    if not filter_parts:
        return source_path

    cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", video_map, "-map", audio_map])
    if video_map == "0:v:0":
        cmd.extend(["-c:v", "copy"])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "18"])
    if audio_map == "0:a:0":
        cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    if source_duration > 0:
        cmd.extend(["-t", f"{source_duration:.6f}"])
    cmd.append(str(output_path))

    _write_debug_text(debug_dir, "packaging.music_watermark.ffmpeg.txt", _format_command(cmd))
    result = await _run_process(
        cmd,
        timeout=_resolve_ffmpeg_timeout(
            source_duration_sec=source_duration,
            multiplier=2.2,
            buffer_sec=420,
            minimum_timeout=900,
        ),
    )
    _write_process_debug(debug_dir, "packaging.music_watermark", result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg music/watermark packaging failed: {result.stderr[-2000:]}")
    return output_path


async def _prepare_multi_track_music_loop(
    *,
    candidate_paths: list[Path],
    output_path: Path,
    debug_dir: Path | None,
) -> Path:
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in candidate_paths:
        key = str(path)
        if key in seen or not path.exists():
            continue
        seen.add(key)
        unique_paths.append(path)
    if not unique_paths:
        raise FileNotFoundError("No usable music tracks for loop_all mode")
    if len(unique_paths) == 1:
        return unique_paths[0]

    cmd = ["ffmpeg", "-y"]
    for path in unique_paths:
        cmd.extend(["-i", str(path)])
    concat_inputs = "".join(f"[{index}:a]" for index in range(len(unique_paths)))
    cmd.extend(
        [
            "-filter_complex",
            f"{concat_inputs}concat=n={len(unique_paths)}:v=0:a=1[aout]",
            "-map",
            "[aout]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ]
    )
    _write_debug_text(debug_dir, "packaging.music_loop_all.ffmpeg.txt", _format_command(cmd))
    loop_duration = max((_probe_duration(path) for path in unique_paths), default=0.0)
    result = await _run_process(
        cmd,
        timeout=_resolve_ffmpeg_timeout(
            source_duration_sec=loop_duration,
            multiplier=1.3,
            buffer_sec=180,
        ),
    )
    _write_process_debug(debug_dir, "packaging.music_loop_all", result)
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg multi-track music loop failed: {result.stderr[-2000:]}")
    return output_path


async def _prepare_packaging_clip(
    source_path: Path,
    output_path: Path,
    *,
    expected_width: int,
    expected_height: int,
) -> Path:
    media_info = _ffprobe_json(source_path)
    has_audio = any(stream.get("codec_type") == "audio" for stream in media_info.get("streams", []))
    duration = _probe_duration(source_path)
    scale_filter = (
        f"scale={expected_width}:{expected_height}:force_original_aspect_ratio=decrease,"
        f"pad={expected_width}:{expected_height}:(ow-iw)/2:(oh-ih)/2:black,"
        "setsar=1,format=yuv420p"
    )

    cmd = ["ffmpeg", "-y", "-i", str(source_path)]
    if not has_audio:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-t",
                f"{max(duration, 0.1):.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )
    cmd.extend(
        [
            "-vf",
            scale_filter,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
        ]
    )
    if not has_audio:
        cmd.extend(["-map", "0:v:0", "-map", "1:a:0", "-shortest"])
    cmd.append(str(output_path))

    result = await _run_process(cmd, timeout=get_settings().ffmpeg_timeout_sec)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg packaging clip prepare failed: {result.stderr[-2000:]}")
    return output_path


def _watermark_overlay_position(position: str) -> tuple[str, str]:
    mapping = {
        "top_left": ("24", "24"),
        "top_right": ("main_w-overlay_w-24", "24"),
        "bottom_left": ("24", "main_h-overlay_h-24"),
        "bottom_right": ("main_w-overlay_w-24", "main_h-overlay_h-24"),
    }
    return mapping.get(position, mapping["top_right"])


async def _normalize_rendered_output(
    output_path: Path,
    *,
    expected_width: int,
    expected_height: int,
    debug_dir: Path | None,
) -> None:
    settings = get_settings()
    info = _probe_video_stream(output_path)
    _write_debug_json(debug_dir, "output.pre_normalize.ffprobe.json", info)

    if _is_expected_output(info, expected_width, expected_height):
        return

    if info["rotation_cw"] != 0:
        stripped = output_path.with_name(f"{output_path.stem}.rotation0{output_path.suffix}")
        strip_cmd = [
            "ffmpeg",
            "-y",
            "-display_rotation:v:0",
            "0",
            "-i",
            str(output_path),
            "-c",
            "copy",
            str(stripped),
        ]
        _write_debug_text(debug_dir, "strip.ffmpeg.txt", _format_command(strip_cmd))
        strip_result = await _run_process(strip_cmd, timeout=min(settings.ffmpeg_timeout_sec, 300))
        _write_process_debug(debug_dir, "strip", strip_result)
        if strip_result.returncode == 0 and stripped.exists():
            stripped_info = _probe_video_stream(stripped)
            _write_debug_json(debug_dir, "output.post_strip.ffprobe.json", stripped_info)
            if _is_expected_output(stripped_info, expected_width, expected_height):
                _finalize_output_file(stripped, output_path)
                return

    if _can_bake_rotation(info, expected_width, expected_height):
        baked = output_path.with_name(f"{output_path.stem}.normalized{output_path.suffix}")
        bake_filter = _rotation_filter_for_cw(info["rotation_cw"])
        bake_cmd = [
            "ffmpeg",
            "-y",
            "-noautorotate",
            "-i",
            str(output_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            bake_filter,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "copy",
            str(baked),
        ]
        _write_debug_text(debug_dir, "normalize.ffmpeg.txt", _format_command(bake_cmd))
        bake_result = await _run_process(bake_cmd, timeout=settings.ffmpeg_timeout_sec)
        _write_process_debug(debug_dir, "normalize", bake_result)
        if bake_result.returncode == 0 and baked.exists():
            baked_info = _probe_video_stream(baked)
            _write_debug_json(debug_dir, "output.post_normalize.ffprobe.json", baked_info)
            if _is_expected_output(baked_info, expected_width, expected_height):
                _finalize_output_file(baked, output_path)
                return

    final_info = _probe_video_stream(output_path)
    _write_debug_json(debug_dir, "output.final.ffprobe.json", final_info)
    raise RuntimeError(
        "Rendered output orientation is still inconsistent after normalization. "
        f"expected={expected_width}x{expected_height}, "
        f"actual_raw={final_info['width']}x{final_info['height']}, "
        f"actual_display={final_info['display_width']}x{final_info['display_height']}, "
        f"rotation={final_info['rotation_raw']}. "
        f"Debug dir: {debug_dir or output_path.parent}"
    )


async def _run_process(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    loop = asyncio.get_running_loop()
    safe_cmd, temp_files = _materialize_long_filter_complex_args(cmd)
    try:
        return await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                safe_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            ),
        )
    finally:
        for path in temp_files:
            path.unlink(missing_ok=True)


def _materialize_long_filter_complex_args(cmd: list[str]) -> tuple[list[str], list[Path]]:
    if os.name != "nt" or len(_format_command(cmd)) < _WINDOWS_CMD_SOFT_LIMIT:
        return list(cmd), []

    rewritten = list(cmd)
    temp_files: list[Path] = []
    index = 0
    while index < len(rewritten) - 1:
        if rewritten[index] != "-filter_complex":
            index += 1
            continue
        script_path = Path(tempfile.gettempdir()) / f"roughcut_ffmpeg_{uuid.uuid4().hex}.fcs"
        script_path.write_text(str(rewritten[index + 1]), encoding="utf-8")
        rewritten[index] = "-filter_complex_script"
        rewritten[index + 1] = str(script_path)
        temp_files.append(script_path)
        index += 2
    return rewritten, temp_files


def _finalize_output_file(source_path: Path, target_path: Path) -> None:
    if source_path == target_path:
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        source_path.replace(target_path)
    except OSError:
        if target_path.exists():
            target_path.unlink()
        shutil.move(str(source_path), str(target_path))


def _probe_video_stream(path: Path) -> dict[str, Any]:
    stream = next(
        (s for s in _ffprobe_json(path).get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    return _describe_stream(stream)


def _probe_duration(path: Path) -> float:
    info = _ffprobe_json(path)
    return float(info.get("format", {}).get("duration", 0.0) or 0.0)


def _ffprobe_json(path: Path) -> dict[str, Any]:
    settings = get_settings()
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=min(settings.ffmpeg_timeout_sec, 60),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr[-500:]}")
    return json.loads(result.stdout or "{}")


def _describe_stream(stream: dict[str, Any]) -> dict[str, Any]:
    width = int(stream.get("width", 0) or 0)
    height = int(stream.get("height", 0) or 0)
    rotation_raw = 0
    has_display_matrix = False

    for side_data in stream.get("side_data_list", []):
        if side_data.get("side_data_type") == "Display Matrix":
            has_display_matrix = True
        if "rotation" in side_data:
            rotation_raw = int(side_data["rotation"])
            break

    if rotation_raw == 0:
        rot_tag = stream.get("tags", {}).get("rotate")
        if rot_tag not in (None, ""):
            rotation_raw = int(rot_tag)

    rotation_cw = rotation_raw % 360
    if rotation_cw in (90, 270):
        display_width, display_height = height, width
    else:
        display_width, display_height = width, height

    return {
        "width": width,
        "height": height,
        "display_width": display_width,
        "display_height": display_height,
        "rotation_raw": rotation_raw,
        "rotation_cw": rotation_cw,
        "has_display_matrix": has_display_matrix,
        "tags": stream.get("tags", {}),
    }


def _is_expected_output(info: dict[str, Any], expected_width: int, expected_height: int) -> bool:
    return (
        info["width"] == expected_width
        and info["height"] == expected_height
        and info["rotation_cw"] == 0
    )


def _can_bake_rotation(info: dict[str, Any], expected_width: int, expected_height: int) -> bool:
    return (
        info["rotation_cw"] in (90, 180, 270)
        and info["display_width"] == expected_width
        and info["display_height"] == expected_height
        and (info["width"], info["height"]) != (expected_width, expected_height)
    )


def _rotation_filter_for_cw(rotation_cw: int) -> str:
    mapping = {
        90: "transpose=1",
        180: "hflip,vflip",
        270: "transpose=2",
    }
    try:
        return mapping[rotation_cw]
    except KeyError as exc:
        raise ValueError(f"Unsupported rotation for baking: {rotation_cw}") from exc


def _format_command(cmd: list[str]) -> str:
    return subprocess.list2cmdline(cmd)


def _write_debug_json(debug_dir: Path | None, name: str, payload: Any) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_debug_text(debug_dir: Path | None, name: str, content: str) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / name).write_text(content, encoding="utf-8")


def _write_process_debug(
    debug_dir: Path | None,
    prefix: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / f"{prefix}.stdout.log").write_text(result.stdout or "", encoding="utf-8")
    (debug_dir / f"{prefix}.stderr.log").write_text(result.stderr or "", encoding="utf-8")

