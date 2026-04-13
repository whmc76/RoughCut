from __future__ import annotations

import asyncio
import functools
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
from roughcut.packaging.library import (
    resolve_insert_effective_duration,
    resolve_insert_motion_behavior,
    resolve_insert_prepare_duration,
    resolve_insert_transition_overlap,
)


logger = logging.getLogger(__name__)
_WINDOWS_CMD_SOFT_LIMIT = 30000
_DEFAULT_SMART_EFFECT_STYLE = "smart_effect_commercial"
_LEGACY_SMART_EFFECT_STYLE_ALIASES = {
    "smart_effect_rhythm": _DEFAULT_SMART_EFFECT_STYLE,
    "smart_effect_ai_impact": "smart_effect_commercial_ai",
}

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


def _audio_encode_args(*, sample_rate: int | None = None, channels: int | None = None) -> list[str]:
    settings = get_settings()
    args = ["-c:a", "aac", "-b:a", str(settings.render_audio_bitrate or "192k")]
    if sample_rate is not None:
        args.extend(["-ar", str(sample_rate)])
    if channels is not None:
        args.extend(["-ac", str(channels)])
    return args


def _video_encode_args(*, prefer_hardware: bool = True) -> list[str]:
    settings = get_settings()
    encoder = _resolve_video_encoder(prefer_hardware=prefer_hardware)
    if encoder == "h264_qsv":
        quality = max(1, min(51, int(settings.render_crf or 19)))
        return [
            "-c:v",
            "h264_qsv",
            "-preset",
            "medium",
            "-global_quality",
            str(quality),
            "-look_ahead",
            "0",
            "-pix_fmt",
            "nv12",
        ]
    if encoder == "h264_nvenc":
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            str(settings.render_nvenc_preset or "p5"),
            "-cq:v",
            str(int(settings.render_nvenc_cq or 21)),
            "-b:v",
            "0",
            "-pix_fmt",
            "yuv420p",
        ]
    if encoder == "h264_amf":
        qp = max(0, min(51, int(settings.render_crf or 19)))
        return [
            "-c:v",
            "h264_amf",
            "-usage",
            "transcoding",
            "-quality",
            "balanced",
            "-rc",
            "cqp",
            "-qp_i",
            str(qp),
            "-qp_p",
            str(min(51, qp + 2)),
            "-qp_b",
            str(min(51, qp + 4)),
            "-pix_fmt",
            "yuv420p",
        ]
    return [
        "-c:v",
        "libx264",
        "-preset",
        str(settings.render_cpu_preset or "veryfast"),
        "-crf",
        str(int(settings.render_crf or 19)),
        "-pix_fmt",
        "yuv420p",
    ]


def _resolve_video_encoder(*, prefer_hardware: bool) -> str:
    requested = str(get_settings().render_video_encoder or "auto").strip().lower()
    if requested not in {"auto", "libx264", "h264_qsv", "h264_nvenc", "h264_amf"}:
        logger.warning("Unknown render_video_encoder=%s; falling back to auto", requested)
        requested = "auto"
    if requested == "libx264":
        return "libx264"
    if requested == "h264_qsv":
        if _qsv_available():
            return "h264_qsv"
        logger.warning("render_video_encoder=h264_qsv requested but QSV is unavailable; falling back to libx264")
        return "libx264"
    if requested == "h264_nvenc":
        if _nvenc_available():
            return "h264_nvenc"
        logger.warning("render_video_encoder=h264_nvenc requested but NVENC is unavailable; falling back to libx264")
        return "libx264"
    if requested == "h264_amf":
        if _amf_available():
            return "h264_amf"
        logger.warning("render_video_encoder=h264_amf requested but AMF is unavailable; falling back to libx264")
        return "libx264"
    if prefer_hardware and _qsv_available():
        return "h264_qsv"
    if prefer_hardware and _amf_available():
        return "h264_amf"
    if prefer_hardware and _nvenc_available():
        return "h264_nvenc"
    return "libx264"


@functools.lru_cache(maxsize=1)
def _nvenc_available() -> bool:
    return _nvidia_device_available() and _ffmpeg_encoder_available("h264_nvenc")


@functools.lru_cache(maxsize=1)
def _qsv_available() -> bool:
    return _intel_device_available() and _ffmpeg_encoder_available("h264_qsv")


@functools.lru_cache(maxsize=1)
def _amf_available() -> bool:
    return _amd_device_available() and _ffmpeg_encoder_available("h264_amf")


@functools.lru_cache(maxsize=1)
def _nvidia_device_available() -> bool:
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(str(result.stdout or "").strip())


@functools.lru_cache(maxsize=1)
def _host_graphics_adapter_text() -> str:
    probe_commands: list[list[str]] = []
    if os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            probe_commands.append(
                [
                    powershell,
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterCompatibility,VideoProcessor | Format-List",
                ]
            )
    else:
        lspci = shutil.which("lspci")
        if lspci is not None:
            probe_commands.append([lspci])

    for cmd in probe_commands:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        haystack = f"{result.stdout}\n{result.stderr}".strip().lower()
        if haystack:
            return haystack
    return ""


@functools.lru_cache(maxsize=1)
def _intel_device_available() -> bool:
    haystack = _host_graphics_adapter_text()
    return "intel" in haystack or "uhd graphics" in haystack or "iris" in haystack


@functools.lru_cache(maxsize=1)
def _amd_device_available() -> bool:
    haystack = _host_graphics_adapter_text()
    return "advanced micro devices" in haystack or "amd" in haystack or "radeon" in haystack


@functools.lru_cache(maxsize=8)
def _ffmpeg_encoder_available(encoder_name: str) -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    stdout = str(result.stdout or "").lower()
    return encoder_name.lower() in stdout


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
    get_settings()

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
    section_choreography = render_plan.get("section_choreography") or {}
    choreographed_subtitles = _build_choreographed_subtitle_items(
        subtitle_items,
        subtitles_plan=render_plan.get("subtitles") or {},
    ) if subtitle_items and render_plan.get("subtitles") else []
    video_transform_accents = _build_video_transform_editing_accents(
        editing_accents,
        subtitle_items=choreographed_subtitles,
        section_choreography=section_choreography,
    )
    segment_filters, video_label, audio_label = _build_segment_filter_chain(
        keep_segments,
        transpose_suffix=transpose_suffix,
        editing_accents=editing_accents,
        section_choreography=section_choreography,
        subtitle_items=choreographed_subtitles,
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
    audio_label = "afinal"
    audio_map = f"[{audio_label}]"

    if video_transform_accents.get("emphasis_overlays") and _should_apply_smart_effect_video_transforms(render_plan.get("avatar_commentary") or {}):
        smart_effect_filters, video_label = _build_smart_effect_video_filters(
            video_label,
            video_transform_accents,
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

    overlay_plan = _build_overlay_only_editing_accents(
        overlay_editing_accents if isinstance(overlay_editing_accents, dict) else editing_accents,
        section_choreography=section_choreography,
    )
    needs_timed_overlays = bool(
        subtitle_items
        or overlay_plan.get("emphasis_overlays")
        or overlay_plan.get("sound_effects")
    )
    if needs_timed_overlays and not packaging_enabled:
        overlay_filter_parts, overlay_video_label, overlay_audio_label = await _build_timed_overlay_filter_chain(
            render_plan=render_plan,
            subtitle_items=subtitle_items,
            overlay_plan=overlay_plan,
            output_path=output_path,
            render_w=render_w,
            render_h=render_h,
            video_label=video_label,
            audio_label=audio_label,
            debug_dir=debug_dir,
        )
        if overlay_filter_parts:
            filter_parts.extend(overlay_filter_parts)
            video_label = overlay_video_label
            audio_label = overlay_audio_label
            video_map = f"[{video_label}]"
            audio_map = f"[{audio_label}]"

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
        audio_map,
        *_video_encode_args(),
        *_audio_encode_args(),
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

    if needs_timed_overlays and packaging_enabled:
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
    section_choreography: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
) -> tuple[list[str], str, str]:
    parts: list[str] = []
    transition_map = _resolve_transition_map(
        keep_segments,
        editing_accents.get("transitions") or {},
        section_choreography=section_choreography,
        subtitle_items=subtitle_items,
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
    *,
    section_choreography: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
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
        transition_mode = _resolve_choreography_transition_mode(
            keep_segments,
            boundary_index=index,
            section_choreography=section_choreography,
        )
        if transition_mode == "accented":
            transition_duration = min(0.22, transition_duration * 1.18)
        elif transition_mode == "protect":
            transition_duration = max(0.08, transition_duration * 0.72)
        elif transition_mode == "restrained":
            transition_duration = max(0.08, transition_duration * 0.9)
        transition_duration *= _resolve_boundary_transition_energy_multiplier(
            keep_segments,
            boundary_index=index,
            section_choreography=section_choreography,
        )
        transition_duration *= _resolve_boundary_unit_transition_multiplier(
            keep_segments,
            boundary_index=index,
            subtitle_items=subtitle_items,
            section_choreography=section_choreography,
        )
        transition_duration = min(0.24, transition_duration)
        if transition_duration < 0.08:
            continue
        resolved[index] = round(transition_duration, 3)
    return resolved


def _resolve_boundary_transition_energy_multiplier(
    keep_segments: list[dict[str, Any]],
    *,
    boundary_index: int,
    section_choreography: dict[str, Any] | None = None,
) -> float:
    boundary_time_sec = _resolve_boundary_time_sec(keep_segments, boundary_index=boundary_index)
    section = _section_choreography_for_time(boundary_time_sec, section_choreography=section_choreography)
    if section is None:
        return 1.0
    bias = float(section.get("transition_energy_bias", 0.0) or 0.0)
    return max(0.72, min(1.18, 1.0 + bias))


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
        parts.append(
            f"[{current_audio}][{fx_label}]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[{mixed_label}]"
        )
        current_audio = mixed_label
    return parts, current_audio


def _resolve_choreography_transition_mode(
    keep_segments: list[dict[str, Any]],
    *,
    boundary_index: int,
    section_choreography: dict[str, Any] | None = None,
) -> str | None:
    sections = list((section_choreography or {}).get("sections") or [])
    if not sections or boundary_index < 0 or boundary_index >= len(keep_segments) - 1:
        return None

    boundary_time_sec = _resolve_boundary_time_sec(keep_segments, boundary_index=boundary_index)

    nearest_mode: str | None = None
    nearest_distance = float("inf")
    for section in sections:
        if not isinstance(section, dict):
            continue
        anchor_sec = float(section.get("transition_anchor_sec", section.get("start_sec", 0.0)) or 0.0)
        distance = abs(anchor_sec - boundary_time_sec)
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_mode = str(section.get("transition_mode") or "").strip() or None
    return nearest_mode


def _resolve_boundary_time_sec(
    keep_segments: list[dict[str, Any]],
    *,
    boundary_index: int,
) -> float:
    if boundary_index < 0:
        return 0.0
    boundary_time_sec = 0.0
    for segment in keep_segments[: boundary_index + 1]:
        boundary_time_sec += max(0.0, float(segment.get("end", 0.0) or 0.0) - float(segment.get("start", 0.0) or 0.0))
    return boundary_time_sec


def _resolve_boundary_unit_transition_multiplier(
    keep_segments: list[dict[str, Any]],
    *,
    boundary_index: int,
    subtitle_items: list[dict[str, Any]] | None = None,
    section_choreography: dict[str, Any] | None = None,
) -> float:
    if not subtitle_items or boundary_index < 0 or boundary_index >= len(keep_segments) - 1:
        return 1.0

    boundary_time_sec = _resolve_boundary_time_sec(keep_segments, boundary_index=boundary_index)
    best_multiplier = 1.0
    best_score = 0.0
    for item in subtitle_items:
        if not isinstance(item, dict):
            continue
        unit_role = str(item.get("subtitle_unit_role") or "").strip().lower()
        if unit_role not in {"lead", "focus"}:
            continue
        start_time = max(0.0, float(item.get("start_time", 0.0) or 0.0))
        end_time = max(start_time + 0.2, float(item.get("end_time", start_time) or start_time))
        midpoint = (start_time + end_time) / 2.0
        distance = min(
            abs(boundary_time_sec - start_time),
            abs(boundary_time_sec - midpoint),
            abs(boundary_time_sec - end_time),
        )
        if distance > 1.0:
            continue
        section = _section_choreography_for_time(midpoint, section_choreography=section_choreography)
        if section is None:
            section = _section_choreography_for_time(boundary_time_sec, section_choreography=section_choreography)
        transform_intensity = _resolve_unit_transform_intensity(unit_role=unit_role, section=section)
        proximity = max(0.0, 1.0 - distance / 1.0)
        role_drive = {
            "lead": 0.08,
            "focus": 0.045,
        }.get(unit_role, 0.04)
        context_drive = (transform_intensity - 1.0) * 0.72
        multiplier = max(0.82, min(1.28, 1.0 + (role_drive + context_drive) * proximity))
        score = proximity * max(0.85, transform_intensity) * (1.15 if unit_role == "lead" else 1.0)
        if score > best_score:
            best_score = score
            best_multiplier = multiplier
    return best_multiplier


def _section_choreography_for_time(
    time_sec: float,
    *,
    section_choreography: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    for section in list((section_choreography or {}).get("sections") or []):
        if not isinstance(section, dict):
            continue
        start_sec = float(section.get("start_sec", 0.0) or 0.0)
        end_sec = float(section.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= time_sec <= end_sec + 1e-6:
            return section
    return None


def _subtitle_profile_for_time(
    time_sec: float,
    *,
    subtitles_plan: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    for profile in list((subtitles_plan or {}).get("section_profiles") or []):
        if not isinstance(profile, dict):
            continue
        start_sec = float(profile.get("start_sec", 0.0) or 0.0)
        end_sec = float(profile.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= time_sec <= end_sec + 1e-6:
            return profile
    return None


def _build_choreographed_subtitle_items(
    subtitle_items: list[dict[str, Any]] | None,
    *,
    subtitles_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not subtitle_items:
        return []
    choreographed = sorted(
        [dict(item) for item in subtitle_items if isinstance(item, dict)],
        key=lambda item: float(item.get("start_time", 0.0) or 0.0),
    )
    if not isinstance(subtitles_plan, dict) or not list(subtitles_plan.get("section_profiles") or []):
        return choreographed

    default_linger_sec = max(0.0, float(subtitles_plan.get("default_linger_sec", 0.04) or 0.04))
    default_guard_sec = max(0.03, float(subtitles_plan.get("timing_guard_sec", 0.07) or 0.07))
    for index, item in enumerate(choreographed):
        start_time = float(item.get("start_time", 0.0) or 0.0)
        end_time = max(start_time, float(item.get("end_time", start_time) or start_time))
        midpoint = (start_time + end_time) / 2.0
        profile = _subtitle_profile_for_time(midpoint, subtitles_plan=subtitles_plan)
        if not profile:
            continue
        item["subtitle_section_role"] = str(profile.get("role") or "")
        if profile.get("style_name"):
            item["style_name"] = str(profile.get("style_name"))
        if profile.get("motion_style"):
            item["motion_style"] = str(profile.get("motion_style"))
        if profile.get("margin_v_delta") not in (None, ""):
            item["margin_v_delta"] = int(profile.get("margin_v_delta") or 0)

        unit_choreography = _resolve_subtitle_unit_choreography(item)
        if unit_choreography.get("style_name"):
            item["style_name"] = str(unit_choreography["style_name"])
        if unit_choreography.get("motion_style"):
            item["motion_style"] = str(unit_choreography["motion_style"])
        if unit_choreography.get("margin_v_delta") not in (None, ""):
            item["margin_v_delta"] = int(unit_choreography["margin_v_delta"] or 0)
        linger_value = profile.get("linger_sec")
        guard_value = profile.get("guard_sec")
        linger_sec = max(0.0, float(default_linger_sec if linger_value is None else linger_value))
        guard_sec = max(0.03, float(default_guard_sec if guard_value is None else guard_value))
        linger_sec += float(unit_choreography.get("linger_delta_sec", 0.0) or 0.0)
        guard_sec = max(0.03, guard_sec + float(unit_choreography.get("guard_delta_sec", 0.0) or 0.0))
        if linger_sec <= 0.0:
            continue
        extended_end = end_time + linger_sec
        profile_end_sec = max(start_time, float(profile.get("end_sec", extended_end) or extended_end))
        extended_end = min(extended_end, profile_end_sec + 0.02)
        if index + 1 < len(choreographed):
            next_start = float(choreographed[index + 1].get("start_time", extended_end) or extended_end)
            extended_end = min(extended_end, max(start_time + 0.05, next_start - guard_sec))
        item["end_time"] = round(max(end_time, extended_end), 3)
    return choreographed


def _resolve_subtitle_unit_choreography(item: dict[str, Any]) -> dict[str, Any]:
    section_role = str(item.get("subtitle_section_role") or "").strip().lower()
    unit_role = str(item.get("subtitle_unit_role") or "").strip().lower()
    if not unit_role:
        return {}
    if section_role == "hook":
        if unit_role == "lead":
            current_style_name = str(item.get("style_name") or "").strip()
            return {
                "motion_style": "motion_strobe",
                "style_name": (
                    "sale_banner"
                    if current_style_name in {"teaser_glow", "cobalt_pop", "sale_banner"}
                    else item.get("style_name")
                ),
                "margin_v_delta": int(item.get("margin_v_delta", 0) or 0) - 2,
                "linger_delta_sec": 0.04,
                "guard_delta_sec": -0.01,
            }
        if unit_role == "support":
            return {
                "motion_style": "motion_slide",
                "style_name": "coupon_green",
                "margin_v_delta": int(item.get("margin_v_delta", 0) or 0) + 6,
                "linger_delta_sec": -0.02,
                "guard_delta_sec": 0.02,
            }
    if section_role == "detail":
        if unit_role == "setup":
            return {
                "motion_style": "motion_slide",
                "style_name": "clean_box",
                "margin_v_delta": int(item.get("margin_v_delta", 0) or 0),
                "linger_delta_sec": -0.01,
            }
        if unit_role == "focus":
            return {
                "motion_style": "motion_pop",
                "style_name": "cyber_orange",
                "margin_v_delta": int(item.get("margin_v_delta", 0) or 0) + 8,
                "linger_delta_sec": 0.05,
                "guard_delta_sec": -0.01,
            }
    if section_role == "cta":
        if unit_role == "action":
            return {
                "motion_style": "motion_static",
                "style_name": "white_minimal",
                "margin_v_delta": int(item.get("margin_v_delta", 0) or 0) + 6,
                "linger_delta_sec": 0.0,
            }
        if unit_role == "signoff":
            return {
                "motion_style": "motion_echo",
                "style_name": "soft_shadow",
                "margin_v_delta": int(item.get("margin_v_delta", 0) or 0) + 14,
                "linger_delta_sec": -0.02,
                "guard_delta_sec": 0.02,
            }
    return {}


def _choreography_allows_overlay(
    time_sec: float,
    *,
    section_choreography: dict[str, Any] | None = None,
) -> bool:
    section = _section_choreography_for_time(time_sec, section_choreography=section_choreography)
    if section is None:
        return True
    if bool(section.get("cta_protection")):
        return False
    return str(section.get("overlay_focus") or "medium") != "none"


def _choreography_allows_sound(
    time_sec: float,
    *,
    section_choreography: dict[str, Any] | None = None,
) -> bool:
    section = _section_choreography_for_time(time_sec, section_choreography=section_choreography)
    if section is None:
        return True
    return not bool(section.get("cta_protection"))


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
    max_full_transforms = max(0, int(tokens.get("max_full_transforms") or 0))
    primary_transform_indexes: set[int] = set()
    if max_full_transforms > 0:
        ranked_indexes = [
            index
            for index, overlay in sorted(
                enumerate(overlays),
                key=lambda item: (
                    -float(item[1].get("transform_intensity", 1.0) or 1.0),
                    0 if str(item[1].get("text") or "").strip() else 1,
                    -max(
                        0.0,
                        float(item[1].get("end_time") or 0.0) - float(item[1].get("start_time") or 0.0),
                    ),
                    float(item[1].get("start_time") or 0.0),
                ),
            )
        ]
        primary_transform_indexes = set(ranked_indexes[:max_full_transforms])

    for index, overlay in enumerate(overlays):
        overlay_tokens = _resolve_overlay_video_transform_tokens(tokens, overlay)
        start_time = max(0.0, float(overlay.get("start_time") or 0.0))
        end_time = max(start_time + 0.24, float(overlay.get("end_time") or start_time + 1.0))
        attack_end = min(end_time, start_time + max(0.08, (end_time - start_time) * 0.38))
        enable_expr = f"between(t\\,{start_time}\\,{end_time})"
        output_label = f"vsmart{index}"
        if index in primary_transform_indexes:
            zoom_expr = (
                f"if(lte(in_time\\,{start_time})\\,1\\,"
                f"if(lte(in_time\\,{attack_end})\\,1+((in_time-{start_time})/{max(attack_end - start_time, 0.01)})*{overlay_tokens['zoom_peak']}\\,"
                f"1+(({end_time}-in_time)/{max(end_time - attack_end, 0.01)})*{overlay_tokens['zoom_decay']}))"
            )
            parts.append(
                f"[{current_video}]scale=iw*{overlay_tokens['pre_scale']}:ih*{overlay_tokens['pre_scale']},"
                f"crop=w=iw/{overlay_tokens['pre_scale']}:h=ih/{overlay_tokens['pre_scale']}:"
                f"x='(iw-iw/{overlay_tokens['pre_scale']})/2':y='(ih-ih/{overlay_tokens['pre_scale']})/2',"
                f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d=1:s={zoom_size}:fps=30000/1001,"
                f"eq=contrast={overlay_tokens['contrast']}:saturation={overlay_tokens['saturation']}:brightness={overlay_tokens['brightness']},"
                f"unsharp={overlay_tokens['unsharp']},"
                f"drawbox=x=0:y=0:w=iw:h=ih:color={overlay_tokens['flash_color']}:t=fill:enable='{enable_expr}':replace=0"
                f"[{output_label}]"
            )
        else:
            parts.append(
                f"[{current_video}]drawbox=x=0:y=0:w=iw:h=ih:color={overlay_tokens['flash_color']}:t=fill:"
                f"enable='{enable_expr}':replace=0[{output_label}]"
            )
        current_video = output_label
    return parts, current_video


def _resolve_overlay_video_transform_tokens(
    base_tokens: dict[str, Any],
    overlay: dict[str, Any],
) -> dict[str, Any]:
    intensity = max(0.65, min(1.35, float(overlay.get("transform_intensity", 1.0) or 1.0)))
    resolved = dict(base_tokens)
    resolved["zoom_peak"] = round(float(base_tokens.get("zoom_peak", 0.08) or 0.08) * intensity, 4)
    resolved["zoom_decay"] = round(float(base_tokens.get("zoom_decay", 0.04) or 0.04) * intensity, 4)
    resolved["contrast"] = round(1.0 + (float(base_tokens.get("contrast", 1.04) or 1.04) - 1.0) * intensity, 4)
    resolved["saturation"] = round(1.0 + (float(base_tokens.get("saturation", 1.08) or 1.08) - 1.0) * intensity, 4)
    resolved["brightness"] = round(float(base_tokens.get("brightness", 0.015) or 0.015) * intensity, 4)
    resolved["flash_color"] = _scale_flash_color_alpha(
        str(base_tokens.get("flash_color") or "white@0.08"),
        intensity=intensity,
    )
    return resolved


def _scale_flash_color_alpha(color: str, *, intensity: float) -> str:
    value = str(color or "").strip()
    if "@" not in value:
        return value
    prefix, alpha = value.rsplit("@", 1)
    try:
        alpha_value = float(alpha)
    except ValueError:
        return value
    scaled_alpha = max(0.01, min(0.28, alpha_value * intensity))
    return f"{prefix}@{scaled_alpha:.3f}".rstrip("0").rstrip(".")


def _build_overlay_only_editing_accents(
    editing_accents: dict[str, Any] | None,
    *,
    subtitle_items: list[dict[str, Any]] | None = None,
    section_choreography: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(editing_accents or {})
    emphasis_overlays = _prune_events_by_choreography_density([
        dict(item)
        for item in base.get("emphasis_overlays") or []
        if _choreography_allows_overlay(
            float((item or {}).get("start_time", 0.0) or 0.0),
            section_choreography=section_choreography,
        )
    ], section_choreography=section_choreography)
    sound_effects = _prune_events_by_choreography_density([
        dict(item)
        for item in base.get("sound_effects") or []
        if _choreography_allows_sound(
            float((item or {}).get("start_time", 0.0) or 0.0),
            section_choreography=section_choreography,
        )
    ], section_choreography=section_choreography)
    synthesized = _synthesize_subtitle_unit_accents(
        subtitle_items,
        existing_overlays=emphasis_overlays,
        existing_sounds=sound_effects,
        section_choreography=section_choreography,
    )
    return {
        "style": _normalize_smart_effect_style(str(base.get("style") or "")),
        "emphasis_overlays": emphasis_overlays + synthesized["emphasis_overlays"],
        "sound_effects": sound_effects + synthesized["sound_effects"],
    }


def _synthesize_subtitle_unit_accents(
    subtitle_items: list[dict[str, Any]] | None,
    *,
    existing_overlays: list[dict[str, Any]],
    existing_sounds: list[dict[str, Any]],
    section_choreography: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if not subtitle_items:
        return {"emphasis_overlays": [], "sound_effects": []}

    synthesized_overlays: list[dict[str, Any]] = []
    synthesized_sounds: list[dict[str, Any]] = []
    for item in subtitle_items:
        if not isinstance(item, dict):
            continue
        unit_role = str(item.get("subtitle_unit_role") or "").strip().lower()
        if unit_role not in {"lead", "focus", "action"}:
            continue
        start_time = max(0.0, float(item.get("start_time", 0.0) or 0.0))
        end_time = max(start_time + 0.2, float(item.get("end_time", start_time) or start_time))
        midpoint = (start_time + end_time) / 2.0
        if not _choreography_allows_overlay(midpoint, section_choreography=section_choreography):
            continue
        if _choreography_suppresses_unit_accent(
            midpoint,
            unit_role=unit_role,
            section_choreography=section_choreography,
        ):
            continue
        text = str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        if not text:
            continue
        if any(abs(float(existing.get("start_time", 0.0) or 0.0) - start_time) <= 0.18 for existing in existing_overlays + synthesized_overlays):
            continue
        overlay_duration = {
            "lead": 0.56,
            "focus": 0.62,
            "action": 0.5,
        }.get(unit_role, 0.52)
        overlay_text = text if unit_role != "action" else ""
        synthesized_overlays.append(
            {
                "text": overlay_text,
                "start_time": round(start_time, 3),
                "end_time": round(min(end_time, start_time + overlay_duration), 3),
                "source": "subtitle_unit",
                "subtitle_unit_role": unit_role,
            }
        )
        if not _choreography_allows_sound(midpoint, section_choreography=section_choreography):
            continue
        if any(abs(float(existing.get("start_time", 0.0) or 0.0) - start_time) <= 0.16 for existing in existing_sounds + synthesized_sounds):
            continue
        sound_tokens = {
            "lead": {"frequency": 1180, "volume": 0.058, "duration_sec": 0.1},
            "focus": {"frequency": 1020, "volume": 0.052, "duration_sec": 0.09},
            "action": {"frequency": 840, "volume": 0.04, "duration_sec": 0.08},
        }.get(unit_role, {"frequency": 960, "volume": 0.045, "duration_sec": 0.08})
        synthesized_sounds.append(
            {
                "start_time": round(start_time, 3),
                **sound_tokens,
                "source": "subtitle_unit",
                "subtitle_unit_role": unit_role,
            }
        )
    return {
        "emphasis_overlays": _prune_events_by_choreography_density(
            synthesized_overlays,
            section_choreography=section_choreography,
        ),
        "sound_effects": _prune_events_by_choreography_density(
            synthesized_sounds,
            section_choreography=section_choreography,
        ),
    }


def _prune_events_by_choreography_density(
    events: list[dict[str, Any]],
    *,
    section_choreography: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not events:
        return []
    pruned: list[dict[str, Any]] = []
    last_kept_by_section: dict[int, float] = {}
    for event in sorted(events, key=lambda item: float((item or {}).get("start_time", 0.0) or 0.0)):
        start_time = float((event or {}).get("start_time", 0.0) or 0.0)
        section = _section_choreography_for_time(start_time, section_choreography=section_choreography)
        section_index = int((section or {}).get("index", -1) or -1)
        density_bias = int((section or {}).get("overlay_density_bias", 0) or 0)
        if density_bias <= -1:
            last_kept = last_kept_by_section.get(section_index)
            if last_kept is not None and start_time - last_kept < 1.05:
                continue
        pruned.append(event)
        last_kept_by_section[section_index] = start_time
    return pruned


def _choreography_suppresses_unit_accent(
    time_sec: float,
    *,
    unit_role: str,
    section_choreography: dict[str, Any] | None = None,
) -> bool:
    section = _section_choreography_for_time(time_sec, section_choreography=section_choreography)
    density_bias = int((section or {}).get("overlay_density_bias", 0) or 0)
    if density_bias <= -1 and str(unit_role or "").strip().lower() in {"focus", "action"}:
        return True
    return False


def _build_video_transform_editing_accents(
    editing_accents: dict[str, Any] | None,
    *,
    subtitle_items: list[dict[str, Any]] | None,
    section_choreography: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(editing_accents or {})
    existing_overlays = [dict(item) for item in base.get("emphasis_overlays") or [] if isinstance(item, dict)]
    synthesized_overlays: list[dict[str, Any]] = []
    for item in subtitle_items or []:
        if not isinstance(item, dict):
            continue
        unit_role = str(item.get("subtitle_unit_role") or "").strip().lower()
        if unit_role not in {"lead", "focus"}:
            continue
        start_time = max(0.0, float(item.get("start_time", 0.0) or 0.0))
        end_time = max(start_time + 0.24, float(item.get("end_time", start_time) or start_time))
        midpoint = (start_time + end_time) / 2.0
        section = _section_choreography_for_time(midpoint, section_choreography=section_choreography)
        if not _choreography_allows_overlay(midpoint, section_choreography=section_choreography):
            continue
        if any(abs(float(existing.get("start_time", 0.0) or 0.0) - start_time) <= 0.18 for existing in existing_overlays + synthesized_overlays):
            continue
        transform_intensity = _resolve_unit_transform_intensity(unit_role=unit_role, section=section)
        synthesized_overlays.append(
            {
                "text": str(item.get("text_final") or ""),
                "start_time": round(start_time, 3),
                "end_time": round(min(end_time, start_time + (0.72 if unit_role == "lead" else 0.64)), 3),
                "source": "subtitle_unit_video",
                "subtitle_unit_role": unit_role,
                "transition_mode": str((section or {}).get("transition_mode") or ""),
                "packaging_intent": str((section or {}).get("packaging_intent") or ""),
                "transform_intensity": round(transform_intensity, 3),
            }
        )
    return {
        **base,
        "emphasis_overlays": existing_overlays + synthesized_overlays,
        "sound_effects": [dict(item) for item in base.get("sound_effects") or [] if isinstance(item, dict)],
    }


def _resolve_unit_transform_intensity(
    *,
    unit_role: str,
    section: dict[str, Any] | None,
) -> float:
    intensity = {
        "lead": 1.14,
        "focus": 1.08,
    }.get(str(unit_role or "").strip().lower(), 1.0)
    transition_mode = str((section or {}).get("transition_mode") or "").strip().lower()
    packaging_intent = str((section or {}).get("packaging_intent") or "").strip().lower()
    if transition_mode == "accented":
        intensity *= 1.12
    elif transition_mode == "protect":
        intensity *= 0.74
    elif transition_mode == "restrained":
        intensity *= 0.92
    if packaging_intent in {"hook_focus", "detail_support"}:
        intensity *= 1.06
    elif packaging_intent == "cta_protect":
        intensity *= 0.72
    return max(0.65, min(1.35, intensity))


async def _apply_timed_overlays_to_video(
    source_path: Path,
    *,
    output_path: Path,
    render_plan: dict[str, Any],
    subtitle_items: list[dict] | None,
    overlay_editing_accents: dict[str, Any] | None,
    debug_dir: Path | None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source_info = _probe_video_stream(source_path)
    render_w = int(source_info.get("display_width") or source_info.get("width") or 0)
    render_h = int(source_info.get("display_height") or source_info.get("height") or 0)
    overlay_plan = _build_overlay_only_editing_accents(
        overlay_editing_accents,
        section_choreography=render_plan.get("section_choreography") or {},
    )
    filter_parts, video_label, audio_label = await _build_timed_overlay_filter_chain(
        render_plan=render_plan,
        subtitle_items=subtitle_items,
        overlay_plan=overlay_plan,
        output_path=output_path,
        render_w=render_w,
        render_h=render_h,
        video_label="0:v",
        audio_label="0:a",
        debug_dir=debug_dir,
    )

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
        f"[{video_label}]",
        "-map",
        f"[{audio_label}]",
        "-shortest",
        str(output_path),
    ]
    if video_label == "0:v":
        cmd[-1:-1] = ["-c:v", "copy"]
    else:
        cmd[-1:-1] = _video_encode_args()
    if audio_label == "0:a":
        cmd[-1:-1] = ["-c:a", "copy"]
    else:
        cmd[-1:-1] = _audio_encode_args()
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


async def _build_timed_overlay_filter_chain(
    *,
    render_plan: dict[str, Any],
    subtitle_items: list[dict] | None,
    overlay_plan: dict[str, Any] | None,
    output_path: Path,
    render_w: int,
    render_h: int,
    video_label: str,
    audio_label: str,
    debug_dir: Path | None,
) -> tuple[list[str], str, str]:
    from roughcut.media.subtitles import escape_path_for_ffmpeg_filter, write_ass_file

    settings = get_settings()
    overlay_plan = overlay_plan or {}
    choreographed_subtitles = _build_choreographed_subtitle_items(
        subtitle_items,
        subtitles_plan=render_plan.get("subtitles") or {},
    ) if subtitle_items and render_plan.get("subtitles") else []

    filter_parts: list[str] = []

    if subtitle_items and render_plan.get("subtitles"):
        subtitle_margin_override = await _resolve_subtitle_margin_with_avatar(
            expected_width=render_w,
            expected_height=render_h,
            avatar_plan=render_plan.get("avatar_commentary") or {},
        )
        ass_path = output_path.parent / f"{output_path.stem}.subtitle.ass"
        write_ass_file(
            choreographed_subtitles,
            ass_path,
            style_name=str((render_plan.get("subtitles") or {}).get("style") or "bold_yellow_outline"),
            font_name=settings.subtitle_font,
            font_size=settings.subtitle_font_size,
            text_color_rgb=settings.subtitle_color,
            outline_color_rgb=settings.subtitle_outline_color,
            outline_width=settings.subtitle_outline_width,
            margin_v_override=subtitle_margin_override,
            motion_style=str((render_plan.get("subtitles") or {}).get("motion_style") or "motion_static"),
            play_res_x=render_w,
            play_res_y=render_h,
        )
        escaped = escape_path_for_ffmpeg_filter(ass_path)
        filter_parts.append(f"[{video_label}]subtitles='{escaped}'[vsub]")
        video_label = "vsub"

    if overlay_plan.get("emphasis_overlays"):
        overlay_filters, video_label = _build_emphasis_overlay_filters(video_label, overlay_plan)
        filter_parts.extend(overlay_filters)

    if overlay_plan.get("sound_effects"):
        sfx_filters, audio_label = _build_sound_effect_filters(audio_label, overlay_plan)
        filter_parts.extend(sfx_filters)

    return filter_parts, video_label, audio_label


def _resolve_effect_overlay_tokens(style: str) -> dict[str, Any]:
    mapping: dict[str, dict[str, Any]] = {
        _DEFAULT_SMART_EFFECT_STYLE: {
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
        "smart_effect_atmosphere": {
            "fontsize": 74,
            "fontcolor": "0xfff6ea",
            "boxcolor": "0x1a1310@0.46",
            "boxborderw": 18,
            "borderw": 2,
            "bordercolor": "0xf0c38a@0.34",
            "y_ratio": 0.19,
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
        "smart_effect_commercial_ai": {
            "fontsize": 92,
            "fontcolor": "0xf8fbff",
            "boxcolor": "0x111317@0.62",
            "boxborderw": 28,
            "borderw": 3,
            "bordercolor": "0xff6a3d@0.58",
            "y_ratio": 0.145,
        },
        "smart_effect_punch_ai": {
            "fontsize": 94,
            "fontcolor": "0xf7fbff",
            "boxcolor": "0x0b1220@0.68",
            "boxborderw": 28,
            "borderw": 3,
            "bordercolor": "0xff6a3d@0.62",
            "y_ratio": 0.145,
        },
        "smart_effect_glitch_ai": {
            "fontsize": 90,
            "fontcolor": "0xf5f7ff",
            "boxcolor": "0x11162f@0.72",
            "boxborderw": 26,
            "borderw": 3,
            "bordercolor": "0x7b8dff@0.6",
            "y_ratio": 0.15,
        },
        "smart_effect_cinematic_ai": {
            "fontsize": 82,
            "fontcolor": "0xfff4e8",
            "boxcolor": "0x140e09@0.52",
            "boxborderw": 22,
            "borderw": 2,
            "bordercolor": "0xe2b471@0.42",
            "y_ratio": 0.18,
        },
        "smart_effect_atmosphere_ai": {
            "fontsize": 86,
            "fontcolor": "0xfff8ef",
            "boxcolor": "0x18120e@0.56",
            "boxborderw": 24,
            "borderw": 2,
            "bordercolor": "0xf0c38a@0.48",
            "y_ratio": 0.175,
        },
        "smart_effect_minimal_ai": {
            "fontsize": 72,
            "fontcolor": "white",
            "boxcolor": "black@0.36",
            "boxborderw": 16,
            "borderw": 1,
            "bordercolor": "white@0.18",
            "y_ratio": 0.19,
        },
    }
    normalized = _normalize_smart_effect_style(style)
    return mapping.get(normalized, mapping[_DEFAULT_SMART_EFFECT_STYLE])


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
        "max_full_transforms": 2,
    }
    mapping: dict[str, dict[str, Any]] = {
        _DEFAULT_SMART_EFFECT_STYLE: {
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
        "smart_effect_atmosphere": {
            **base,
            "pre_scale": 1.11,
            "zoom_peak": 0.045,
            "zoom_decay": 0.022,
            "contrast": 1.025,
            "saturation": 1.035,
            "brightness": 0.006,
            "unsharp": "5:5:0.38:3:3:0.0",
            "flash_color": "0xffe0b2@0.05",
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
        "smart_effect_commercial_ai": {
            **base,
            "pre_scale": 1.17,
            "zoom_peak": 0.095,
            "zoom_decay": 0.05,
            "contrast": 1.04,
            "saturation": 1.075,
            "brightness": 0.012,
            "unsharp": "5:5:0.48:3:3:0.0",
            "flash_color": "0xfff2cc@0.14",
            "max_full_transforms": 2,
        },
        "smart_effect_punch_ai": {
            **base,
            "pre_scale": 1.18,
            "zoom_peak": 0.11,
            "zoom_decay": 0.06,
            "contrast": 1.045,
            "saturation": 1.08,
            "brightness": 0.012,
            "unsharp": "5:5:0.5:3:3:0.0",
            "flash_color": "0xfff2cc@0.16",
            "max_full_transforms": 2,
        },
        "smart_effect_glitch_ai": {
            **base,
            "pre_scale": 1.17,
            "zoom_peak": 0.1,
            "zoom_decay": 0.055,
            "contrast": 1.05,
            "saturation": 1.12,
            "brightness": 0.01,
            "unsharp": "5:5:0.52:3:3:0.0",
            "flash_color": "0x9f8cff@0.16",
            "max_full_transforms": 2,
        },
        "smart_effect_cinematic_ai": {
            **base,
            "pre_scale": 1.12,
            "zoom_peak": 0.06,
            "zoom_decay": 0.03,
            "contrast": 1.028,
            "saturation": 1.03,
            "brightness": 0.006,
            "unsharp": "5:5:0.4:3:3:0.0",
            "flash_color": "0xf2c07a@0.06",
            "max_full_transforms": 2,
        },
        "smart_effect_atmosphere_ai": {
            **base,
            "pre_scale": 1.13,
            "zoom_peak": 0.065,
            "zoom_decay": 0.032,
            "contrast": 1.03,
            "saturation": 1.04,
            "brightness": 0.008,
            "unsharp": "5:5:0.42:3:3:0.0",
            "flash_color": "0xffdfb2@0.08",
            "max_full_transforms": 2,
        },
        "smart_effect_minimal_ai": {
            **base,
            "pre_scale": 1.09,
            "zoom_peak": 0.028,
            "zoom_decay": 0.016,
            "contrast": 1.015,
            "saturation": 1.02,
            "brightness": 0.002,
            "unsharp": "5:5:0.28:3:3:0.0",
            "flash_color": "white@0.04",
            "max_full_transforms": 1,
        },
    }
    normalized = _normalize_smart_effect_style(style)
    return mapping.get(normalized, mapping[_DEFAULT_SMART_EFFECT_STYLE])


def _normalize_smart_effect_style(style: str) -> str:
    normalized = str(style or "").strip().lower()
    if not normalized:
        return _DEFAULT_SMART_EFFECT_STYLE
    return _LEGACY_SMART_EFFECT_STYLE_ALIASES.get(normalized, normalized)


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
    source_duration = _probe_duration(source_path)
    if source_duration <= 0.0:
        return source_path
    insert_after_sec = _resolve_insert_after_sec(
        float(insert_plan.get("insert_after_sec", 0.0) or 0.0),
        source_duration=source_duration,
        insert_plan=insert_plan,
    )

    prepared_insert = output_path.with_name("insert_asset.prepared.mp4")
    insert_source_duration = _probe_duration(Path(insert_plan["path"]))
    prepare_insert_duration = resolve_insert_prepare_duration(insert_plan, source_duration=insert_source_duration)
    effective_insert_duration = resolve_insert_effective_duration(insert_plan, source_duration=insert_source_duration)
    transition_overlap = resolve_insert_transition_overlap(
        insert_plan,
        runtime_duration_sec=effective_insert_duration,
        insert_after_sec=insert_after_sec,
        source_duration=source_duration,
    )
    entry_overlap_sec = float(transition_overlap.get("entry_sec", 0.0) or 0.0)
    exit_overlap_sec = float(transition_overlap.get("exit_sec", 0.0) or 0.0)
    await _prepare_packaging_clip(
        Path(insert_plan["path"]),
        prepared_insert,
        expected_width=expected_width,
        expected_height=expected_height,
        trim_duration_sec=prepare_insert_duration,
    )
    insert_video_filter, insert_audio_filter = _build_insert_packaging_filter_chain(
        insert_plan=insert_plan,
        runtime_duration_sec=effective_insert_duration,
    )

    filter_parts = [
        "[0:v]split[vpre][vpost]",
        "[0:a]asplit[apre][apost]",
        f"[vpre]trim=start=0:end={insert_after_sec},setpts=PTS-STARTPTS[v0]",
        f"[apre]atrim=start=0:end={insert_after_sec},asetpts=PTS-STARTPTS[a0]",
        f"[vpost]trim=start={insert_after_sec},setpts=PTS-STARTPTS[v2]",
        f"[apost]atrim=start={insert_after_sec},asetpts=PTS-STARTPTS[a2]",
        f"[1:v]{insert_video_filter}[v1]",
        f"[1:a]{insert_audio_filter}[a1]",
    ]
    if entry_overlap_sec > 0:
        filter_parts.append(
            f"[v0][v1]xfade=transition=fade:duration={entry_overlap_sec:.3f}:offset={max(0.0, insert_after_sec - entry_overlap_sec):.3f}[v01]"
        )
        filter_parts.append(f"[a0][a1]acrossfade=d={entry_overlap_sec:.3f}:c1=tri:c2=tri[a01]")
        current_video = "v01"
        current_audio = "a01"
        current_duration = insert_after_sec + effective_insert_duration - entry_overlap_sec
    else:
        filter_parts.append("[v0][a0][v1][a1]concat=n=2:v=1:a=1[v01][a01]")
        current_video = "v01"
        current_audio = "a01"
        current_duration = insert_after_sec + effective_insert_duration

    if exit_overlap_sec > 0:
        filter_parts.append(
            f"[{current_video}][v2]xfade=transition=fade:duration={exit_overlap_sec:.3f}:offset={max(0.0, current_duration - exit_overlap_sec):.3f}[vout]"
        )
        filter_parts.append(f"[{current_audio}][a2]acrossfade=d={exit_overlap_sec:.3f}:c1=tri:c2=tri[aout]")
    else:
        filter_parts.append(f"[{current_video}][{current_audio}][v2][a2]concat=n=2:v=1:a=1[vout][aout]")
    filter_complex = ";".join(filter_parts)
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
        *_video_encode_args(),
        *_audio_encode_args(),
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


def _build_insert_packaging_filter_chain(
    *,
    insert_plan: dict[str, Any] | None,
    runtime_duration_sec: float,
) -> tuple[str, str]:
    transition_style = str((insert_plan or {}).get("insert_transition_style") or "straight_cut").strip().lower()
    transition_mode = str((insert_plan or {}).get("insert_transition_mode") or "restrained").strip().lower()
    playback_rate = float(resolve_insert_motion_behavior(insert_plan).get("playback_rate", 1.0) or 1.0)
    fade_tokens = _resolve_insert_transition_tokens(
        transition_style,
        runtime_duration_sec=runtime_duration_sec,
        transition_mode=transition_mode,
    )

    video_filters = ["setpts=PTS-STARTPTS"]
    audio_filters = ["asetpts=PTS-STARTPTS"]

    if abs(playback_rate - 1.0) > 1e-3:
        video_filters.append(f"setpts=PTS/{playback_rate:.3f}")
        audio_filters.append(f"atempo={playback_rate:.3f}")

    if fade_tokens["video_fade_in"] > 0:
        video_filters.append(f"fade=t=in:st=0:d={fade_tokens['video_fade_in']:.3f}")
    if fade_tokens["video_fade_out"] > 0:
        video_filters.append(
            f"fade=t=out:st={max(0.0, runtime_duration_sec - fade_tokens['video_fade_out']):.3f}:d={fade_tokens['video_fade_out']:.3f}"
        )
    if fade_tokens["audio_fade_in"] > 0:
        audio_filters.append(f"afade=t=in:st=0:d={fade_tokens['audio_fade_in']:.3f}")
    if fade_tokens["audio_fade_out"] > 0:
        audio_filters.append(
            f"afade=t=out:st={max(0.0, runtime_duration_sec - fade_tokens['audio_fade_out']):.3f}:d={fade_tokens['audio_fade_out']:.3f}"
        )

    return ",".join(video_filters), ",".join(audio_filters)


def _resolve_insert_transition_tokens(
    transition_style: str,
    *,
    runtime_duration_sec: float,
    transition_mode: str = "restrained",
) -> dict[str, float]:
    overlap = resolve_insert_transition_overlap(
        {
            "insert_transition_style": transition_style,
            "insert_transition_mode": transition_mode,
        },
        runtime_duration_sec=runtime_duration_sec,
    )
    max_fade = float(overlap.get("entry_sec", 0.0) or 0.0)
    return {
        "video_fade_in": round(max_fade, 3),
        "video_fade_out": round(max_fade, 3),
        "audio_fade_in": round(min(max_fade, 0.08), 3),
        "audio_fade_out": round(min(max_fade, 0.08), 3),
    }


def _resolve_insert_after_sec(
    insert_after_sec: float,
    *,
    source_duration: float,
    insert_plan: dict[str, Any] | None = None,
) -> float:
    max_insert_sec = max(0.0, source_duration - 0.1)
    resolved_sec = max(0.0, min(float(insert_after_sec or 0.0), max_insert_sec))
    broll_window = (insert_plan or {}).get("broll_window") or {}
    if not isinstance(broll_window, dict):
        return resolved_sec

    window_start = float(broll_window.get("start_sec", resolved_sec) or resolved_sec)
    window_end = float(broll_window.get("end_sec", resolved_sec) or resolved_sec)
    window_anchor = float(broll_window.get("anchor_sec", resolved_sec) or resolved_sec)
    if window_end < window_start:
        window_start, window_end = window_end, window_start
    window_start = max(0.0, min(window_start, max_insert_sec))
    window_end = max(window_start, min(window_end, max_insert_sec))
    if window_anchor < window_start - 1e-6 or window_anchor > window_end + 1e-6:
        window_anchor = max(window_start, min(window_anchor, window_end))

    if resolved_sec < window_start - 1e-6 or resolved_sec > window_end + 1e-6:
        resolved_sec = window_anchor
    return max(window_start, min(resolved_sec, window_end))


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

    filter_parts: list[str] = []
    concat_inputs = ""
    for index in range(len(prepared_paths)):
        filter_parts.append(
            f"[{index}:v]scale={expected_width}:{expected_height}:force_original_aspect_ratio=decrease,"
            f"pad={expected_width}:{expected_height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,format=yuv420p[v{index}]"
        )
        filter_parts.append(
            f"[{index}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=N/SR/TB[a{index}]"
        )
        concat_inputs += f"[v{index}][a{index}]"
    cmd.extend(
        [
            "-filter_complex",
            f"{';'.join(filter_parts)};{concat_inputs}concat=n={len(prepared_paths)}:v=1:a=1[vout][aout]",
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            *_video_encode_args(),
            *_audio_encode_args(),
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
        bgm_volume_expr = _build_music_volume_expression(
            base_volume=volume,
            duck_windows=list(music_plan.get("duck_windows") or []),
        )
        entry_fade_sec = float(music_plan.get("music_entry_fade_sec", 0.0) or 0.0)
        if enter_sec > 0:
            delay_ms = int(round(enter_sec * 1000))
            filter_parts.append(
                f"[{next_input_index}:a]volume='{bgm_volume_expr}',highpass=f=120,lowpass=f=6000,adelay={delay_ms}|{delay_ms}"
                f"{',afade=t=in:st=' + f'{enter_sec:.3f}' + ':d=' + f'{entry_fade_sec:.3f}' if entry_fade_sec > 0 else ''}[bgm_pre]"
            )
        else:
            filter_parts.append(
                f"[{next_input_index}:a]volume='{bgm_volume_expr}',highpass=f=120,lowpass=f=6000"
                f"{',afade=t=in:st=0:d=' + f'{entry_fade_sec:.3f}' if entry_fade_sec > 0 else ''}[bgm_pre]"
            )
        filter_parts.append(
            "[bgm_pre][0:a]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350:makeup=1[bgm]"
        )
        filter_parts.append("[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[amixed]")
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
        cmd.extend(_video_encode_args())
    if audio_map == "0:a:0":
        cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend(_audio_encode_args())
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


def _build_music_volume_expression(
    *,
    base_volume: float,
    duck_windows: list[dict[str, Any]],
) -> str:
    expr = f"{float(base_volume):.3f}"
    for window in sorted(
        [dict(item) for item in duck_windows if isinstance(item, dict)],
        key=lambda item: float(item.get("start_sec", 0.0) or 0.0),
        reverse=True,
    ):
        start_sec = max(0.0, float(window.get("start_sec", 0.0) or 0.0))
        end_sec = max(start_sec, float(window.get("end_sec", start_sec) or start_sec))
        target_volume = max(0.0, float(window.get("target_volume", base_volume) or base_volume))
        expr = f"if(between(t\\,{start_sec:.3f}\\,{end_sec:.3f})\\,{target_volume:.3f}\\,{expr})"
    return expr


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
            *_audio_encode_args(),
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
    trim_duration_sec: float | None = None,
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
    if trim_duration_sec is not None and float(trim_duration_sec or 0.0) > 0.0:
        cmd.extend(["-t", f"{float(trim_duration_sec):.3f}"])
    cmd.extend(
        [
            "-vf",
            scale_filter,
            *_video_encode_args(),
            *_audio_encode_args(sample_rate=48000, channels=2),
        ]
    )
    if not has_audio:
        cmd.extend(["-map", "0:v:0", "-map", "1:a:0", "-shortest"])
    cmd.append(str(output_path))

    result = await _run_process(cmd, timeout=get_settings().ffmpeg_timeout_sec)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg packaging clip prepare failed: {result.stderr[-2000:]}")
    return output_path


async def _concat_prepared_bookends(
    prepared_paths: list[Path],
    *,
    output_path: Path,
    debug_dir: Path | None,
) -> bool:
    if len(prepared_paths) <= 1:
        return False

    concat_list = output_path.with_name(f"{output_path.stem}.concat.txt")
    concat_lines = [
        "file '{}'".format(path.resolve().as_posix().replace("'", r"'\''"))
        for path in prepared_paths
    ]
    concat_list.write_text("\n".join(concat_lines), encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c",
        "copy",
        str(output_path),
    ]
    _write_debug_text(debug_dir, "packaging.bookends.concat.ffmpeg.txt", _format_command(cmd))
    try:
        result = await _run_process(
            cmd,
            timeout=_resolve_ffmpeg_timeout(
                source_duration_sec=max((_probe_duration(path) for path in prepared_paths), default=0.0),
                multiplier=0.35,
                buffer_sec=90,
                minimum_timeout=120,
            ),
        )
    finally:
        concat_list.unlink(missing_ok=True)
    _write_process_debug(debug_dir, "packaging.bookends.concat", result)
    if result.returncode != 0 or not output_path.exists():
        logger.info("Falling back to re-encoded intro/outro packaging after concat copy failed")
        return False
    return True


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
            *_video_encode_args(),
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
    resolved = path.resolve()
    stat = resolved.stat()
    return _ffprobe_json_cached(str(resolved), int(stat.st_mtime_ns), int(stat.st_size))


@functools.lru_cache(maxsize=512)
def _ffprobe_json_cached(path_str: str, _mtime_ns: int, _size: int) -> dict[str, Any]:
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
            path_str,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=min(settings.ffmpeg_timeout_sec, 60),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path_str}: {result.stderr[-500:]}")
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

