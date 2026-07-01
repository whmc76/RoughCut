from __future__ import annotations

import asyncio
import copy
from contextlib import suppress
import functools
import hashlib
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
from roughcut.edit.editorial_timeline import editorial_keep_segments, normalize_keep_segments_payloads
from roughcut.edit.render_plan import (
    render_plan_avatar_commentary,
    render_plan_delivery,
    render_plan_loudness,
    render_plan_video_transform,
    render_plan_voice_processing,
)
from roughcut.edit.packaging_timeline import (
    packaging_timeline_focus_plan,
    packaging_timeline_hyperframes,
    packaging_timeline_insert_plan,
    packaging_timeline_local_audio_cues,
    packaging_timeline_music_plan,
    resolve_packaging_timeline_payload,
)
from roughcut.edit.subtitle_surfaces import subtitle_display_rule_text
from roughcut import hyperframes
from roughcut.packaging.library import (
    resolve_insert_effective_duration,
    resolve_insert_motion_behavior,
    resolve_insert_prepare_duration,
    resolve_insert_transition_overlap,
)
from roughcut.runtime_paths import resolve_runtime_media_path
from roughcut.utils.asyncio_subprocess import close_asyncio_subprocess_transport


logger = logging.getLogger(__name__)
_WINDOWS_CMD_SOFT_LIMIT = 30000
_DEFAULT_SMART_EFFECT_STYLE = "smart_effect_commercial"
_RENAMED_SMART_EFFECT_STYLE_KEYS = {
    "smart_effect_rhythm": _DEFAULT_SMART_EFFECT_STYLE,
    "smart_effect_ai_impact": "smart_effect_commercial_ai",
}
_RENDER_OVERLAY_LABEL_MAX_CJK_CHARS = 8
_RENDER_OVERLAY_LABEL_MAX_ASCII_CHARS = 14
_RENDER_OVERLAY_SENTENCE_MARKERS = (
    "因为",
    "所以",
    "然后",
    "但是",
    "就是",
    "这个",
    "那个",
    "这里",
    "那边",
    "你看",
    "我们",
    "可以",
    "还是",
    "不太",
    "不算",
)

_EXPORT_RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2160p": (3840, 2160),
}
_DELIVERY_ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
    "4:3": (4, 3),
}
_DELIVERY_FRAME_RATE_PRESETS: dict[str, float] = {
    "24": 24.0,
    "25": 25.0,
    "30": 30.0,
    "50": 50.0,
    "60": 60.0,
}

_TRANSPOSE_MAP = {
    90: ",transpose=1",
    180: ",hflip,vflip",
    270: ",transpose=2",
}

_DEFAULT_TARGET_LUFS = -16.0
_DEFAULT_PEAK_LIMIT_DB = -2.0
_DEFAULT_LRA = 10.0


def _render_packaging_context(render_plan: dict[str, Any] | None) -> dict[str, Any]:
    packaging_timeline = resolve_packaging_timeline_payload(render_plan)
    assets = copy.deepcopy(packaging_timeline.get("packaging") or {})
    assets["insert"] = packaging_timeline_insert_plan(packaging_timeline)
    assets["music"] = packaging_timeline_music_plan(packaging_timeline)
    editing_accents = copy.deepcopy(packaging_timeline.get("editing_accents") or {})
    hyperframes_plan = packaging_timeline_hyperframes(packaging_timeline)
    return {
        "assets": assets,
        "editing_accents": editing_accents,
        "hyperframes": hyperframes_plan,
        "has_packaging_assets": any(assets.get(key) for key in ("intro", "outro", "insert", "watermark", "music")),
        "focus": packaging_timeline_focus_plan(packaging_timeline),
        "chapter_analysis": copy.deepcopy(packaging_timeline.get("chapter_analysis") or {}),
        "audio_cues": packaging_timeline_local_audio_cues(packaging_timeline),
        "section_choreography": copy.deepcopy(packaging_timeline.get("section_choreography") or {}),
        "subtitles": copy.deepcopy(packaging_timeline.get("subtitles") or {}),
    }


def _render_runtime_plan_context(render_plan: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "delivery": render_plan_delivery(render_plan),
        "video_transform": render_plan_video_transform(render_plan),
        "avatar_plan": render_plan_avatar_commentary(render_plan),
        "voice_processing": render_plan_voice_processing(render_plan),
        "loudness": render_plan_loudness(render_plan),
    }


def _normalize_rotation_cw(value: Any) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(float(value)) % 360
    except (TypeError, ValueError):
        return None
    return min((0, 90, 180, 270), key=lambda item: min(abs(item - normalized), 360 - abs(item - normalized)))


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


def _bounded_positive_int(value: Any, *, upper: int = 256) -> int:
    try:
        resolved = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(upper, resolved))


def _ffmpeg_filter_thread_args() -> list[str]:
    threads = _bounded_positive_int(getattr(get_settings(), "render_ffmpeg_filter_threads", 0), upper=128)
    return ["-filter_threads", str(threads)] if threads > 0 else []


def _ffmpeg_encode_thread_args(*, default_threads: int | None = None) -> list[str]:
    threads = _bounded_positive_int(getattr(get_settings(), "render_ffmpeg_threads", 0), upper=256)
    if threads <= 0 and default_threads is not None:
        threads = _bounded_positive_int(default_threads, upper=256)
    return ["-threads", str(threads)] if threads > 0 else []


def _ffmpeg_base_cmd() -> list[str]:
    return ["ffmpeg", "-nostdin", "-y", *_ffmpeg_filter_thread_args()]


def _delivery_color_metadata_args() -> list[str]:
    return [
        "-colorspace",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_range",
        "tv",
    ]


def _video_delivery_encode_args(*, prefer_hardware: bool = True, default_threads: int | None = None) -> list[str]:
    return [
        *_video_encode_args(prefer_hardware=prefer_hardware, default_threads=default_threads),
        *_delivery_color_metadata_args(),
    ]


def _replace_video_encode_args_for_software(cmd: list[str], *, default_threads: int | None = 4) -> list[str]:
    rewritten = list(cmd)
    try:
        start = rewritten.index("-c:v")
    except ValueError:
        return rewritten
    end = start + 2
    while end < len(rewritten) and rewritten[end] not in {"-c:a", "-t"}:
        end += 1
    return [
        *rewritten[:start],
        *_video_delivery_encode_args(prefer_hardware=False, default_threads=default_threads),
        *rewritten[end:],
    ]


def _video_encode_args(*, prefer_hardware: bool = True, default_threads: int | None = None) -> list[str]:
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
        *_ffmpeg_encode_thread_args(default_threads=default_threads),
        "-pix_fmt",
        "yuv420p",
    ]


def _prefer_software_encoder_for_source(source_info: dict[str, Any], *, source_duration_sec: float) -> bool:
    if source_duration_sec >= 900:
        return True
    if int(source_info.get("rotation_cw") or 0) in (90, 180, 270):
        return True
    pix_fmt = str(source_info.get("pix_fmt") or "").lower()
    if "10" in pix_fmt or "12" in pix_fmt:
        return True
    color_transfer = str(source_info.get("color_transfer") or "").lower()
    if color_transfer in {"arib-std-b67", "smpte2084"}:
        return True
    return False


def _normalize_color_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _source_is_hdr(source_info: dict[str, Any]) -> bool:
    transfer = _normalize_color_token(source_info.get("color_transfer"))
    return transfer in {"arib-std-b67", "smpte2084"}


def _source_needs_delivery_color_filter(source_info: dict[str, Any]) -> bool:
    if _source_is_hdr(source_info):
        return True
    primaries = _normalize_color_token(source_info.get("color_primaries"))
    matrix = _normalize_color_token(source_info.get("color_space"))
    transfer = _normalize_color_token(source_info.get("color_transfer"))
    color_range = _normalize_color_token(source_info.get("color_range"))
    return (
        primaries not in {"", "unknown", "bt709"}
        or matrix not in {"", "unknown", "bt709"}
        or transfer not in {"", "unknown", "bt709"}
        or color_range in {"pc", "full", "jpeg"}
    )


def _source_setparams_filter(source_info: dict[str, Any]) -> str | None:
    options: list[str] = []
    primaries = _normalize_color_token(source_info.get("color_primaries"))
    transfer = _normalize_color_token(source_info.get("color_transfer"))
    matrix = _normalize_color_token(source_info.get("color_space"))
    color_range = _normalize_color_token(source_info.get("color_range"))
    if _source_is_hdr(source_info):
        primaries = primaries if primaries not in {"", "unknown"} else "bt2020"
        matrix = matrix if matrix not in {"", "unknown"} else "bt2020nc"

    if primaries not in {"", "unknown"}:
        options.append(f"color_primaries={primaries}")
    if transfer not in {"", "unknown"}:
        options.append(f"color_trc={transfer}")
    if matrix not in {"", "unknown"}:
        options.append(f"colorspace={matrix}")
    if color_range in {"pc", "full", "jpeg"}:
        options.append("range=full")
    elif color_range in {"tv", "limited", "mpeg"}:
        options.append("range=limited")
    if not options:
        return None
    return f"setparams={':'.join(options)}"


def _delivery_color_filter_chain(source_info: dict[str, Any]) -> list[str]:
    if not _source_needs_delivery_color_filter(source_info):
        return []

    setparams_filter = _source_setparams_filter(source_info)
    output_options = [
        "primaries=bt709",
        "transfer=bt709",
        "matrix=bt709",
        "range=limited",
    ]
    filters = [setparams_filter] if setparams_filter else []
    if _source_is_hdr(source_info):
        filters.extend(
            [
                "zscale=transfer=linear:npl=100",
                "format=gbrpf32le",
                "zscale=primaries=bt709",
                "tonemap=tonemap=hable:desat=0",
                "zscale=transfer=bt709:matrix=bt709:range=limited",
                "format=yuv420p",
            ]
        )
        return filters
    filters.extend(
        [
            f"zscale={':'.join(output_options)}",
            "format=yuv420p",
        ]
    )
    return filters


def _append_delivery_color_filter(
    parts: list[str],
    input_label: str,
    source_info: dict[str, Any],
    *,
    output_label: str,
) -> str:
    filters = _delivery_color_filter_chain(source_info)
    if not filters:
        return input_label
    parts.append(f"[{input_label}]{','.join(filters)}[{output_label}]")
    return output_label


def _describe_delivery_color_management(source_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": {
            "color_primaries": "bt709",
            "color_transfer": "bt709",
            "color_space": "bt709",
            "color_range": "tv",
            "pix_fmt": "yuv420p",
        },
        "source_is_hdr": _source_is_hdr(source_info),
        "filter_applied": _source_needs_delivery_color_filter(source_info),
        "filter_chain": _delivery_color_filter_chain(source_info),
    }


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
                    "Get-CimInstance Win32_VideoController | Select-Object Name,VideoProcessor | Format-List",
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
    render_plan: dict[str, Any] | None,
    editorial_timeline: dict,
    output_path: Path,
    keep_segments: list[dict[str, Any]] | None = None,
    subtitle_items: list[dict] | None = None,
    overlay_editing_accents: dict[str, Any] | None = None,
    synthesize_subtitle_unit_accents: bool = True,
    progress_callback: Callable[[float], None] | None = None,
    debug_dir: Path | None = None,
    packaging_context: dict[str, Any] | None = None,
    runtime_plan_context: dict[str, Any] | None = None,
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

    resolved_packaging_context = (
        packaging_context if isinstance(packaging_context, dict) else _render_packaging_context(render_plan)
    )
    resolved_runtime_plan_context = (
        runtime_plan_context if isinstance(runtime_plan_context, dict) else _render_runtime_plan_context(render_plan)
    )
    packaging_assets = resolved_packaging_context["assets"]
    packaging_enabled = bool(resolved_packaging_context.get("has_packaging_assets"))
    base_output_path = output_path if not packaging_enabled else output_path.with_name(f"{output_path.stem}.base{output_path.suffix}")

    keep_segments = _resolve_render_keep_segments(
        editorial_timeline,
        explicit_keep_segments=keep_segments,
    )
    if not keep_segments:
        raise ValueError("No keep segments in editorial timeline")

    source_info = _probe_video_stream(source_path)
    _write_debug_json(debug_dir, "source.ffprobe.json", source_info)
    render_delivery = resolved_runtime_plan_context["delivery"]
    target_fps = _resolve_delivery_frame_rate(
        source_fps=float(source_info.get("fps", 0.0) or 0.0),
        delivery=render_delivery,
    )
    target_fps_expr = _ffmpeg_fps_expr(target_fps) if target_fps > 0 else None
    prefer_hardware_encoder = not _prefer_software_encoder_for_source(
        source_info,
        source_duration_sec=source_duration,
    )

    from roughcut.media.rotation import RotationDecision, detect_video_rotation_decision

    manual_video_transform = resolved_runtime_plan_context["video_transform"]
    manual_rotation_cw = _normalize_rotation_cw(manual_video_transform.get("rotation_cw") if manual_video_transform and manual_video_transform.get("rotation_manual") else None)
    rotation_decision = (
        RotationDecision(rotation_cw=manual_rotation_cw, confidence=1.0, source="manual_editor", reason="manual_editor_video_transform")
        if manual_rotation_cw is not None
        else await detect_video_rotation_decision(source_path)
    )
    rotation_cw = rotation_decision.rotation_cw
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
        delivery=render_delivery,
    )

    _write_debug_json(
        debug_dir,
        "orientation.expected.json",
        {
            "source_path": str(source_path),
            "source_rotation_raw": source_info["rotation_raw"],
            "source_rotation_cw": source_info["rotation_cw"],
            "rotation_cw": rotation_cw,
            "manual_rotation_cw": manual_rotation_cw,
            "rotation_decision": rotation_decision.to_dict(),
            "expected_width": expected_w,
            "expected_height": expected_h,
            "target_fps": target_fps,
            "target_fps_expr": target_fps_expr,
            "prefer_hardware_encoder": prefer_hardware_encoder,
            "delivery_color_management": _describe_delivery_color_management(source_info),
        },
    )

    filter_parts: list[str] = []
    editing_accents = resolved_packaging_context["editing_accents"]
    section_choreography = resolved_packaging_context["section_choreography"]
    subtitles_plan = resolved_packaging_context["subtitles"]
    avatar_plan = resolved_runtime_plan_context["avatar_plan"]
    choreographed_subtitles = _build_choreographed_subtitle_items(
        subtitle_items,
        subtitles_plan=subtitles_plan,
    ) if subtitle_items and subtitles_plan else []
    overlay_plan = _build_overlay_only_editing_accents(
        overlay_editing_accents if isinstance(overlay_editing_accents, dict) else editing_accents,
        subtitle_items=subtitle_items,
        section_choreography=section_choreography,
        synthesize_subtitle_unit_accents=synthesize_subtitle_unit_accents,
    )
    hyperframes_plan = _build_runtime_hyperframes_plan(
        packaging_context=resolved_packaging_context,
        render_w=render_w,
        render_h=render_h,
        duration_sec=_keep_segments_duration(keep_segments),
        subtitles_plan=subtitles_plan,
        subtitle_items=choreographed_subtitles or subtitle_items,
        section_choreography=section_choreography,
        overlay_plan=overlay_plan,
        editing_accents=editing_accents,
    )
    editing_accents = hyperframes.effects_from_plan(hyperframes_plan, fallback=editing_accents)
    overlay_plan = hyperframes.overlay_plan_from_plan(hyperframes_plan, fallback=overlay_plan)
    video_transform_accents = _build_video_transform_editing_accents(
        editing_accents,
        subtitle_items=choreographed_subtitles,
        section_choreography=section_choreography,
        synthesize_subtitle_unit_accents=synthesize_subtitle_unit_accents,
    )
    segment_filters, video_label, audio_label = _build_segment_filter_chain(
        keep_segments,
        transpose_suffix=transpose_suffix,
        target_fps_expr=target_fps_expr,
        editing_accents=editing_accents,
        section_choreography=section_choreography,
        subtitle_items=choreographed_subtitles,
    )
    filter_parts.extend(segment_filters)
    video_label = _append_delivery_color_filter(
        filter_parts,
        video_label,
        source_info,
        output_label="vcolor",
    )

    render_voice_processing = resolved_runtime_plan_context["voice_processing"]
    render_loudness = resolved_runtime_plan_context["loudness"]
    if bool(resolved_runtime_plan_context.get("audio_already_mastered")):
        audio_filter = f"[{audio_label}]aresample=async=1:first_pts=0,aformat=sample_rates=48000:channel_layouts=stereo[afinal]"
    else:
        audio_filter = _build_master_audio_filter_chain(
            input_label=audio_label,
            voice_processing=render_voice_processing,
            loudness=render_loudness,
            output_label="afinal",
            allow_noise_reduction=True,
            include_declipping=True,
            include_async_resample=True,
        )
    filter_parts.append(audio_filter)
    video_map = f"[{video_label}]"
    audio_label = "afinal"
    audio_map = f"[{audio_label}]"

    if video_transform_accents.get("emphasis_overlays") and _should_apply_smart_effect_video_transforms(avatar_plan):
        smart_effect_filters, video_label = _build_smart_effect_video_filters(
            video_label,
            video_transform_accents,
            expected_width=render_w,
            expected_height=render_h,
            target_fps_expr=target_fps_expr,
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

    needs_timed_overlays = bool(
        subtitle_items
        or overlay_plan.get("emphasis_overlays")
        or overlay_plan.get("sound_effects")
        or _hyperframes_has_runtime_visual_overlays(hyperframes_plan)
    )
    if needs_timed_overlays and not packaging_enabled:
        overlay_filter_parts, overlay_video_label, overlay_audio_label = await _build_timed_overlay_filter_chain(
            render_plan=None,
            subtitle_items=subtitle_items,
            overlay_plan=overlay_plan,
            choreographed_subtitles=choreographed_subtitles,
            output_path=output_path,
            render_w=render_w,
            render_h=render_h,
            video_label=video_label,
            audio_label=audio_label,
            debug_dir=debug_dir,
            subtitles_plan=subtitles_plan,
            hyperframes_plan=hyperframes_plan,
            packaging_context=None,
            avatar_plan=avatar_plan,
        )
        if overlay_filter_parts:
            filter_parts.extend(overlay_filter_parts)
            video_label = overlay_video_label
            audio_label = overlay_audio_label
            video_map = f"[{video_label}]"
            audio_map = f"[{audio_label}]"

    filter_complex = ";".join(filter_parts)

    cmd = [
        *_ffmpeg_base_cmd(),
        "-noautorotate",
        "-i",
        str(source_path),
        "-filter_complex",
        filter_complex,
        "-map",
        video_map,
        "-map",
        audio_map,
        *_video_delivery_encode_args(prefer_hardware=prefer_hardware_encoder),
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
            target_fps=target_fps,
            debug_dir=debug_dir,
            packaging_context=None,
            packaging_assets=packaging_assets,
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
            render_plan=None,
            subtitle_items=subtitle_items,
            overlay_editing_accents=overlay_plan,
            overlay_plan=overlay_plan,
            choreographed_subtitles=choreographed_subtitles,
            synthesize_subtitle_unit_accents=synthesize_subtitle_unit_accents,
            debug_dir=debug_dir,
            subtitles_plan=subtitles_plan,
            section_choreography=section_choreography,
            hyperframes_plan=hyperframes_plan,
            packaging_context=None,
            avatar_plan=avatar_plan,
        )
        if overlay_output_path != output_path:
            _finalize_output_file(overlay_output_path, output_path)
        current_output = output_path

    return current_output


async def burn_subtitles_on_rendered_video(
    source_path: Path,
    *,
    output_path: Path,
    subtitle_items: list[dict[str, Any]] | list[dict] | None,
    subtitles_plan: dict[str, Any] | None = None,
    debug_dir: Path | None = None,
    packaging_context: dict[str, Any] | None = None,
) -> Path:
    """Burn final subtitles onto an already-rendered candidate without changing audio."""
    subtitle_only_options = {
        key: False
        for key in hyperframes.HYPERFRAMES_OPTION_KEYS
    }
    subtitle_only_options["unified_subtitle_style"] = True
    base_hyperframes = (
        packaging_context.get("hyperframes")
        if isinstance(packaging_context, dict)
        else None
    )
    base_metadata = (
        base_hyperframes.get("metadata")
        if hyperframes.is_hyperframes_plan(base_hyperframes)
        and isinstance(base_hyperframes.get("metadata"), dict)
        else {}
    )
    base_options = (
        hyperframes.normalize_options(base_metadata.get("options"))
        if isinstance(base_metadata.get("options"), dict)
        else {}
    )
    if "unified_subtitle_style" in base_options:
        subtitle_only_options["unified_subtitle_style"] = bool(base_options["unified_subtitle_style"])
    subtitle_style_plan = hyperframes.build_static_packaging_plan(
        subtitles_plan=subtitles_plan,
        editing_accents={},
        options=subtitle_only_options,
        source="roughcut.media.render.final_subtitle_burn_in",
    )
    return await _apply_timed_overlays_to_video(
        source_path,
        output_path=output_path,
        render_plan=None,
        subtitle_items=subtitle_items,
        overlay_editing_accents={},
        overlay_plan={"emphasis_overlays": [], "sound_effects": []},
        choreographed_subtitles=None,
        synthesize_subtitle_unit_accents=False,
        debug_dir=debug_dir,
        subtitles_plan=subtitles_plan,
        section_choreography={},
        hyperframes_plan=subtitle_style_plan,
        packaging_context=None,
        avatar_plan=None,
    )


def _build_segment_filter_chain(
    keep_segments: list[dict[str, Any]],
    *,
    transpose_suffix: str,
    editing_accents: dict[str, Any],
    target_fps_expr: str | None = None,
    section_choreography: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
) -> tuple[list[str], str, str]:
    parts: list[str] = []
    transitions = dict(editing_accents.get("transitions") or {})
    transition_map = _resolve_transition_map(
        keep_segments,
        transitions,
        section_choreography=section_choreography,
        subtitle_items=subtitle_items,
    )
    video_timing_suffix = transpose_suffix
    if target_fps_expr:
        video_timing_suffix = f"{video_timing_suffix},fps={target_fps_expr},settb=AVTB"
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
            transition_name = str(transitions.get("transition") or "fade").strip() or "fade"
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
    overlays = _normalize_render_emphasis_overlays(editing_accents.get("emphasis_overlays") or [])
    for index, overlay in enumerate(overlays):
        text = _escape_drawtext_value(str(overlay.get("text") or ""))
        if not text:
            continue
        overlay_tokens = _resolve_overlay_drawtext_tokens(style_tokens, overlay)
        start_time = max(0.0, float(overlay.get("start_time") or 0.0))
        end_time = max(start_time + 0.85, float(overlay.get("end_time") or start_time + 1.0))
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
            f"fontsize={overlay_tokens['fontsize']}:"
            f"fontcolor={overlay_tokens['fontcolor']}:"
            f"alpha='{alpha_expr}':"
            f"box=1:boxcolor={overlay_tokens['boxcolor']}:boxborderw={overlay_tokens['boxborderw']}:"
            f"borderw={overlay_tokens['borderw']}:bordercolor={overlay_tokens['bordercolor']}:"
            f"shadowcolor={overlay_tokens['shadowcolor']}:shadowx={overlay_tokens['shadowx']}:shadowy={overlay_tokens['shadowy']}:"
            f"x={overlay_tokens['x_expr']}:y=h*{overlay_tokens['y_ratio']}"
            f"[{output_label}]"
        )
        current_video = output_label
    return parts, current_video


def _resolve_overlay_drawtext_tokens(base_tokens: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    tokens = dict(base_tokens)
    tokens.setdefault("x_expr", "(w-text_w)/2")
    tokens.setdefault("shadowcolor", "black@0.20")
    tokens.setdefault("shadowx", 0)
    tokens.setdefault("shadowy", 4)
    tokens["boxborderw"] = max(int(tokens.get("boxborderw") or 0), 18)
    tokens["borderw"] = max(int(tokens.get("borderw") or 0), 3)
    treatment = str(overlay.get("visual_treatment") or "").strip().lower()
    if treatment == "hook_pop":
        tokens["fontsize"] = int(tokens["fontsize"] * 1.04)
        tokens["fontcolor"] = "white"
        tokens["boxcolor"] = "0xff4f9a@0.70"
        tokens["bordercolor"] = "0xffffff@0.72"
        tokens["y_ratio"] = min(float(tokens["y_ratio"]), 0.125)
        tokens["x_expr"] = "(w-text_w)/2"
    elif treatment == "keyword_sticker":
        tokens["fontcolor"] = "0x20130f"
        tokens["boxcolor"] = "0xfff0a6@0.78"
        tokens["bordercolor"] = "0x55f0d0@0.76"
        tokens["x_expr"] = "w-text_w-w*0.055"
        tokens["y_ratio"] = max(float(tokens["y_ratio"]), 0.16)
    elif treatment == "beat_pulse":
        tokens["fontsize"] = int(tokens["fontsize"] * 0.9)
        tokens["fontcolor"] = "white"
        tokens["boxcolor"] = "0x1c73ff@0.66"
        tokens["bordercolor"] = "0xafff4d@0.70"
        tokens["x_expr"] = "w*0.055"
        tokens["y_ratio"] = max(float(tokens["y_ratio"]), 0.2)
    elif treatment == "keyword_pop":
        tokens["fontcolor"] = "white"
        tokens["boxcolor"] = "0x111318@0.66"
        tokens["bordercolor"] = "0x55f0d0@0.70"
    return tokens


def _normalize_render_emphasis_overlays(
    overlays: list[dict[str, Any]] | Any,
    *,
    min_duration_sec: float = 0.85,
    min_spacing_sec: float = 1.8,
    max_count: int = 14,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in sorted(
        [item for item in list(overlays or []) if isinstance(item, dict)],
        key=lambda item: float(item.get("start_time", 0.0) or 0.0),
    ):
        text = _normalize_render_overlay_label_text(str(raw.get("text") or ""))
        if not text:
            continue
        source = str(raw.get("source") or "").strip()
        if source in {"subtitle_unit", "subtitle_unit_video"}:
            continue
        start_time = max(0.0, float(raw.get("start_time", 0.0) or 0.0))
        if normalized and start_time - float(normalized[-1].get("start_time", 0.0) or 0.0) < min_spacing_sec:
            continue
        end_time = max(start_time + min_duration_sec, float(raw.get("end_time", start_time) or start_time))
        item = dict(raw)
        item["text"] = text
        item["start_time"] = round(start_time, 3)
        item["end_time"] = round(end_time, 3)
        normalized.append(item)
        if len(normalized) >= max_count:
            break
    return normalized


def _normalize_render_overlay_label_text(raw: str) -> str:
    text = "".join(str(raw or "").split()).strip("，。！？!?、,.；;：:\"'()（）[]【】<>《》")
    if len(text) < 2:
        return ""
    cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_count = sum(1 for ch in text if ch.isascii() and ch.isalnum())
    if cjk_count and cjk_count > _RENDER_OVERLAY_LABEL_MAX_CJK_CHARS:
        return ""
    if not cjk_count and ascii_count > _RENDER_OVERLAY_LABEL_MAX_ASCII_CHARS:
        return ""
    if cjk_count >= 5 and any(marker in text for marker in _RENDER_OVERLAY_SENTENCE_MARKERS):
        return ""
    if any(mark in text for mark in ("，", "。", "！", "？", ",", ".", "!", "?", "；", ";", "：", ":")):
        return ""
    return text


def _build_smart_effect_video_filters(
    video_label: str,
    editing_accents: dict[str, Any],
    *,
    expected_width: int,
    expected_height: int,
    target_fps_expr: str | None = None,
) -> tuple[list[str], str]:
    overlays = list(editing_accents.get("emphasis_overlays") or [])
    if not overlays:
        return [], video_label

    style = str(editing_accents.get("style") or "smart_effect_rhythm")
    effect_policy = editing_accents.get("effect_policy") if isinstance(editing_accents.get("effect_policy"), dict) else {}
    preserve_color = bool(editing_accents.get("preserve_color")) or bool(effect_policy.get("preserve_color"))
    suppress_full_frame_color_flash = bool(editing_accents.get("suppress_full_frame_color_flash")) or bool(
        effect_policy.get("disallow_full_frame_color_flash")
    )
    if suppress_full_frame_color_flash:
        return [], video_label
    tokens = _resolve_smart_effect_video_tokens(
        style,
        preserve_color=preserve_color,
    )
    zoom_size = f"{expected_width}x{expected_height}"
    zoom_fps_expr = target_fps_expr or "30000/1001"
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
                f"d=1:s={zoom_size}:fps={zoom_fps_expr},"
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
    synthesize_subtitle_unit_accents: bool = False,
) -> dict[str, Any]:
    base = dict(editing_accents or {})
    emphasis_overlays = _normalize_render_emphasis_overlays(_prune_events_by_choreography_density([
        dict(item)
        for item in base.get("emphasis_overlays") or []
        if _choreography_allows_overlay(
            float((item or {}).get("start_time", 0.0) or 0.0),
            section_choreography=section_choreography,
        )
    ], section_choreography=section_choreography))
    sound_effects = _prune_events_by_choreography_density([
        dict(item)
        for item in base.get("sound_effects") or []
        if _choreography_allows_sound(
            float((item or {}).get("start_time", 0.0) or 0.0),
            section_choreography=section_choreography,
        )
    ], section_choreography=section_choreography)
    synthesized = (
        _synthesize_subtitle_unit_accents(
            subtitle_items,
            existing_overlays=emphasis_overlays,
            existing_sounds=sound_effects,
            section_choreography=section_choreography,
        )
        if synthesize_subtitle_unit_accents
        else {"emphasis_overlays": [], "sound_effects": []}
    )
    return {
        "style": _normalize_smart_effect_style(str(base.get("style") or "")),
        "emphasis_overlays": _normalize_render_emphasis_overlays(
            emphasis_overlays + synthesized["emphasis_overlays"]
        ),
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
        text = subtitle_display_rule_text(item)
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
    synthesize_subtitle_unit_accents: bool = False,
) -> dict[str, Any]:
    base = dict(editing_accents or {})
    existing_overlays = _normalize_render_emphasis_overlays(base.get("emphasis_overlays") or [])
    synthesized_overlays: list[dict[str, Any]] = []
    if not synthesize_subtitle_unit_accents:
        return {
            **base,
            "emphasis_overlays": existing_overlays,
            "sound_effects": [dict(item) for item in base.get("sound_effects") or [] if isinstance(item, dict)],
        }
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
    render_plan: dict[str, Any] | None = None,
    subtitle_items: list[dict] | None,
    overlay_editing_accents: dict[str, Any] | None,
    overlay_plan: dict[str, Any] | None = None,
    choreographed_subtitles: list[dict[str, Any]] | None = None,
    synthesize_subtitle_unit_accents: bool = True,
    debug_dir: Path | None,
    subtitles_plan: dict[str, Any] | None = None,
    section_choreography: dict[str, Any] | None = None,
    hyperframes_plan: dict[str, Any] | None = None,
    packaging_context: dict[str, Any] | None = None,
    avatar_plan: dict[str, Any] | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source_info = _probe_video_stream(source_path)
    render_w = int(source_info.get("display_width") or source_info.get("width") or 0)
    render_h = int(source_info.get("display_height") or source_info.get("height") or 0)
    resolved_packaging_context = (
        packaging_context
        if isinstance(packaging_context, dict)
        else (
            _render_packaging_context(render_plan)
            if not (isinstance(subtitles_plan, dict) and isinstance(section_choreography, dict))
            else {}
        )
    )
    resolved_subtitles_plan = (
        dict(subtitles_plan)
        if isinstance(subtitles_plan, dict)
        else dict(resolved_packaging_context.get("subtitles") or {})
    )
    resolved_section_choreography = (
        dict(section_choreography)
        if isinstance(section_choreography, dict)
        else dict(resolved_packaging_context.get("section_choreography") or {})
    )
    resolved_avatar_plan = avatar_plan if isinstance(avatar_plan, dict) else render_plan_avatar_commentary(render_plan)
    resolved_overlay_plan = (
        dict(overlay_plan)
        if isinstance(overlay_plan, dict)
        else _build_overlay_only_editing_accents(
            overlay_editing_accents,
            subtitle_items=subtitle_items,
            section_choreography=resolved_section_choreography,
            synthesize_subtitle_unit_accents=synthesize_subtitle_unit_accents,
        )
    )
    try:
        source_duration = _probe_duration(source_path)
    except Exception:
        source_duration = 0.0
    base_hyperframes_plan = (
        resolved_packaging_context.get("hyperframes")
        if isinstance(resolved_packaging_context, dict)
        else None
    )
    resolved_hyperframes_plan = None
    if hyperframes.is_hyperframes_plan(hyperframes_plan):
        resolved_hyperframes_plan = hyperframes_plan
    elif hyperframes.is_hyperframes_plan(base_hyperframes_plan):
        resolved_hyperframes_plan = _build_runtime_hyperframes_plan(
            packaging_context=resolved_packaging_context,
            render_w=render_w,
            render_h=render_h,
            duration_sec=source_duration,
            subtitles_plan=resolved_subtitles_plan,
            subtitle_items=choreographed_subtitles or subtitle_items,
            section_choreography=resolved_section_choreography,
            overlay_plan=resolved_overlay_plan,
            editing_accents=overlay_editing_accents,
        )
    if hyperframes.is_hyperframes_plan(resolved_hyperframes_plan):
        resolved_overlay_plan = hyperframes.overlay_plan_from_plan(resolved_hyperframes_plan, fallback=resolved_overlay_plan)
    filter_parts: list[str] = []
    video_label = _append_delivery_color_filter(
        filter_parts,
        "0:v",
        source_info,
        output_label="vcolor",
    )
    filter_parts, video_label, audio_label = await _build_timed_overlay_filter_chain(
        render_plan=None,
        subtitle_items=subtitle_items,
        overlay_plan=resolved_overlay_plan,
        choreographed_subtitles=choreographed_subtitles,
        output_path=output_path,
        render_w=render_w,
        render_h=render_h,
        video_label=video_label,
        audio_label="0:a",
        debug_dir=debug_dir,
        initial_filter_parts=filter_parts,
        subtitles_plan=resolved_subtitles_plan,
        hyperframes_plan=resolved_hyperframes_plan,
        packaging_context=None,
        avatar_plan=resolved_avatar_plan,
    )

    if not filter_parts:
        if source_path != output_path:
            _finalize_output_file(source_path, output_path)
        return output_path

    cmd = [
        *_ffmpeg_base_cmd(),
        "-i",
        str(source_path),
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        _ffmpeg_map_label(video_label),
        "-map",
        _ffmpeg_map_label(audio_label),
        "-shortest",
        str(output_path),
    ]
    if video_label == "0:v":
        cmd[-1:-1] = ["-c:v", "copy"]
    else:
        cmd[-1:-1] = _video_delivery_encode_args()
    if audio_label == "0:a":
        cmd[-1:-1] = ["-c:a", "copy"]
    else:
        cmd[-1:-1] = _audio_encode_args()
    cmd[-1:-1] = ["-max_muxing_queue_size", "4096"]
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


def _resolve_render_keep_segments(
    editorial_timeline: dict[str, Any] | None,
    *,
    explicit_keep_segments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    explicit = normalize_keep_segments_payloads(list(explicit_keep_segments or []))
    if explicit:
        return explicit
    return editorial_keep_segments(editorial_timeline)


async def _build_timed_overlay_filter_chain(
    *,
    render_plan: dict[str, Any] | None = None,
    subtitle_items: list[dict] | None,
    overlay_plan: dict[str, Any] | None,
    choreographed_subtitles: list[dict[str, Any]] | None = None,
    output_path: Path,
    render_w: int,
    render_h: int,
    video_label: str,
    audio_label: str,
    debug_dir: Path | None,
    initial_filter_parts: list[str] | None = None,
    subtitles_plan: dict[str, Any] | None = None,
    hyperframes_plan: dict[str, Any] | None = None,
    packaging_context: dict[str, Any] | None = None,
    avatar_plan: dict[str, Any] | None = None,
) -> tuple[list[str], str, str]:
    from roughcut.media.subtitles import escape_path_for_ffmpeg_filter, write_ass_file

    settings = get_settings()
    overlay_plan = overlay_plan or {}
    resolved_packaging_context = (
        packaging_context
        if isinstance(packaging_context, dict)
        else (_render_packaging_context(render_plan) if not isinstance(subtitles_plan, dict) else {})
    )
    resolved_subtitles_plan = (
        dict(subtitles_plan)
        if isinstance(subtitles_plan, dict)
        else dict(resolved_packaging_context.get("subtitles") or {})
    )
    resolved_hyperframes_plan = hyperframes_plan if hyperframes.is_hyperframes_plan(hyperframes_plan) else None
    overlay_plan = hyperframes.overlay_plan_from_plan(resolved_hyperframes_plan, fallback=overlay_plan)
    resolved_avatar_plan = avatar_plan if isinstance(avatar_plan, dict) else render_plan_avatar_commentary(render_plan)
    resolved_choreographed_subtitles = (
        [dict(item) for item in choreographed_subtitles]
        if isinstance(choreographed_subtitles, list)
        else _build_choreographed_subtitle_items(
            subtitle_items,
            subtitles_plan=resolved_subtitles_plan,
        ) if subtitle_items and resolved_subtitles_plan else []
    )

    filter_parts: list[str] = list(initial_filter_parts or [])

    if subtitle_items and resolved_subtitles_plan:
        subtitle_margin_override = await _resolve_subtitle_margin_with_avatar(
            expected_width=render_w,
            expected_height=render_h,
            avatar_plan=resolved_avatar_plan,
        )
        ass_path = output_path.parent / f"{output_path.stem}.subtitle.ass"
        hyperframes_subtitles = hyperframes.apply_subtitle_style_to_items(
            resolved_choreographed_subtitles,
            resolved_hyperframes_plan,
        )
        ass_style_name = hyperframes.subtitle_style_name(
            resolved_hyperframes_plan,
            str(resolved_subtitles_plan.get("style") or "bold_yellow_outline"),
        )
        ass_motion_style = hyperframes.subtitle_motion_style(
            resolved_hyperframes_plan,
            str(resolved_subtitles_plan.get("motion_style") or "motion_static"),
        )
        ass_cache_dir = (debug_dir / "packaging_subcache") if debug_dir is not None else None
        ass_fingerprint = {
            "items": hyperframes_subtitles,
            "style_name": ass_style_name,
            "font_name": settings.subtitle_font,
            "font_size": settings.subtitle_font_size,
            "text_color_rgb": settings.subtitle_color,
            "outline_color_rgb": settings.subtitle_outline_color,
            "outline_width": settings.subtitle_outline_width,
            "margin_v_override": subtitle_margin_override,
            "motion_style": ass_motion_style,
            "play_res_x": render_w,
            "play_res_y": render_h,
        }
        if not await _restore_packaging_subcache(
            cache_dir=ass_cache_dir,
            namespace="subtitle_ass",
            fingerprint=ass_fingerprint,
            output_path=ass_path,
            extension=".ass",
        ):
            write_ass_file(
                hyperframes_subtitles,
                ass_path,
                style_name=ass_style_name,
                font_name=settings.subtitle_font,
                font_size=settings.subtitle_font_size,
                text_color_rgb=settings.subtitle_color,
                outline_color_rgb=settings.subtitle_outline_color,
                outline_width=settings.subtitle_outline_width,
                margin_v_override=subtitle_margin_override,
                motion_style=ass_motion_style,
                play_res_x=render_w,
                play_res_y=render_h,
            )
            await _store_packaging_subcache(
                cache_dir=ass_cache_dir,
                namespace="subtitle_ass",
                fingerprint=ass_fingerprint,
                output_path=ass_path,
                extension=".ass",
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

    hyperframe_filters, video_label = _build_hyperframes_visual_filters(
        video_label,
        resolved_hyperframes_plan,
        render_w=render_w,
        render_h=render_h,
    )
    filter_parts.extend(hyperframe_filters)

    return filter_parts, video_label, audio_label


def _resolve_effect_overlay_tokens(style: str) -> dict[str, Any]:
    mapping: dict[str, dict[str, Any]] = {
        _DEFAULT_SMART_EFFECT_STYLE: {
            "fontsize": 52,
            "fontcolor": "white",
            "boxcolor": "black@0.34",
            "boxborderw": 14,
            "borderw": 1,
            "bordercolor": "black@0.18",
            "y_ratio": 0.14,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_punch": {
            "fontsize": 56,
            "fontcolor": "white",
            "boxcolor": "0x3a0505@0.38",
            "boxborderw": 16,
            "borderw": 2,
            "bordercolor": "0xff874d@0.38",
            "y_ratio": 0.14,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_glitch": {
            "fontsize": 54,
            "fontcolor": "0xeef2ff",
            "boxcolor": "0x11162f@0.42",
            "boxborderw": 15,
            "borderw": 2,
            "bordercolor": "0x6f7fff@0.36",
            "y_ratio": 0.145,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_cinematic": {
            "fontsize": 50,
            "fontcolor": "0xfff4e8",
            "boxcolor": "0x120d08@0.3",
            "boxborderw": 13,
            "borderw": 1,
            "bordercolor": "0xe2b471@0.28",
            "y_ratio": 0.16,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_atmosphere": {
            "fontsize": 52,
            "fontcolor": "0xfff6ea",
            "boxcolor": "0x1a1310@0.34",
            "boxborderw": 14,
            "borderw": 2,
            "bordercolor": "0xf0c38a@0.3",
            "y_ratio": 0.155,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_minimal": {
            "fontsize": 46,
            "fontcolor": "white",
            "boxcolor": "black@0.22",
            "boxborderw": 10,
            "borderw": 1,
            "bordercolor": "white@0.1",
            "y_ratio": 0.16,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_commercial_ai": {
            "fontsize": 58,
            "fontcolor": "0xf8fbff",
            "boxcolor": "0x111317@0.42",
            "boxborderw": 17,
            "borderw": 2,
            "bordercolor": "0xff6a3d@0.44",
            "y_ratio": 0.125,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_punch_ai": {
            "fontsize": 60,
            "fontcolor": "0xf7fbff",
            "boxcolor": "0x0b1220@0.44",
            "boxborderw": 17,
            "borderw": 2,
            "bordercolor": "0xff6a3d@0.46",
            "y_ratio": 0.125,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_glitch_ai": {
            "fontsize": 58,
            "fontcolor": "0xf5f7ff",
            "boxcolor": "0x11162f@0.48",
            "boxborderw": 17,
            "borderw": 2,
            "bordercolor": "0x7b8dff@0.44",
            "y_ratio": 0.13,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_cinematic_ai": {
            "fontsize": 54,
            "fontcolor": "0xfff4e8",
            "boxcolor": "0x140e09@0.36",
            "boxborderw": 15,
            "borderw": 2,
            "bordercolor": "0xe2b471@0.34",
            "y_ratio": 0.15,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_atmosphere_ai": {
            "fontsize": 56,
            "fontcolor": "0xfff8ef",
            "boxcolor": "0x18120e@0.38",
            "boxborderw": 16,
            "borderw": 2,
            "bordercolor": "0xf0c38a@0.38",
            "y_ratio": 0.15,
            "x_expr": "(w-text_w)/2",
        },
        "smart_effect_minimal_ai": {
            "fontsize": 50,
            "fontcolor": "white",
            "boxcolor": "black@0.26",
            "boxborderw": 12,
            "borderw": 1,
            "bordercolor": "white@0.14",
            "y_ratio": 0.155,
            "x_expr": "(w-text_w)/2",
        },
    }
    normalized = _normalize_smart_effect_style(style)
    return mapping.get(normalized, mapping[_DEFAULT_SMART_EFFECT_STYLE])


def _resolve_smart_effect_video_tokens(style: str, *, preserve_color: bool = False) -> dict[str, Any]:
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
    resolved = dict(mapping.get(normalized, mapping[_DEFAULT_SMART_EFFECT_STYLE]))
    # Full-frame emphasis zooms used crop/zoompan and could hide product-detail
    # shots at exactly the moment the footage should be inspected.
    resolved["max_full_transforms"] = 0
    if preserve_color:
        resolved["contrast"] = 1.0
        resolved["saturation"] = 1.0
        resolved["brightness"] = 0.0
        resolved["flash_color"] = _neutralize_flash_color(str(resolved.get("flash_color") or "white@0.08"))
    return resolved


def _neutralize_flash_color(color: str) -> str:
    value = str(color or "").strip()
    if "@" not in value:
        return "white"
    _prefix, alpha = value.rsplit("@", 1)
    return f"white@{alpha}"


def _normalize_smart_effect_style(style: str) -> str:
    normalized = str(style or "").strip().lower()
    if not normalized:
        return _DEFAULT_SMART_EFFECT_STYLE
    return _RENAMED_SMART_EFFECT_STYLE_KEYS.get(normalized, normalized)


def _should_apply_smart_effect_video_transforms(avatar_plan: dict[str, Any]) -> bool:
    integration_mode = str(avatar_plan.get("integration_mode") or "").strip().lower()
    # Once a picture-in-picture avatar has been merged into the plain render, any
    # full-frame crop/zoom will also crop the avatar and subtitle safe area.
    return integration_mode != "picture_in_picture"


def _keep_segments_duration(keep_segments: list[dict[str, Any]] | None) -> float:
    return round(
        sum(
            max(0.0, float(segment.get("end", 0.0) or 0.0) - float(segment.get("start", 0.0) or 0.0))
            for segment in list(keep_segments or [])
            if isinstance(segment, dict)
        ),
        3,
    )


def _build_runtime_hyperframes_plan(
    *,
    packaging_context: dict[str, Any] | None,
    render_w: int,
    render_h: int,
    duration_sec: float,
    subtitles_plan: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]] | list[dict] | None,
    section_choreography: dict[str, Any] | None,
    overlay_plan: dict[str, Any] | None,
    editing_accents: dict[str, Any] | None,
) -> dict[str, Any]:
    base_plan = (packaging_context or {}).get("hyperframes") if isinstance(packaging_context, dict) else None
    base_metadata = base_plan.get("metadata") if hyperframes.is_hyperframes_plan(base_plan) and isinstance(base_plan.get("metadata"), dict) else {}
    return hyperframes.build_render_plan(
        width=render_w,
        height=render_h,
        duration_sec=duration_sec,
        subtitles_plan=subtitles_plan,
        subtitle_items=[dict(item) for item in list(subtitle_items or []) if isinstance(item, dict)],
        overlay_plan=overlay_plan,
        editing_accents=editing_accents,
        focus_plan=(packaging_context or {}).get("focus") if isinstance(packaging_context, dict) else None,
        chapter_analysis=(packaging_context or {}).get("chapter_analysis") if isinstance(packaging_context, dict) else None,
        section_choreography=section_choreography,
        audio_cues=(packaging_context or {}).get("audio_cues") if isinstance(packaging_context, dict) else None,
        options=base_metadata.get("options") if isinstance(base_metadata.get("options"), dict) else None,
        source="roughcut.media.render",
    )


def _hyperframes_has_runtime_visual_overlays(plan: dict[str, Any] | None) -> bool:
    if not hyperframes.is_hyperframes_plan(plan):
        return False
    if hyperframes.progress_bar_enabled(plan):
        return True
    return any(
        str(element.get("track") or "") == "subtitle_emphasis"
        for element in list(plan.get("elements") or [])
        if isinstance(element, dict)
    )


def _build_hyperframes_visual_filters(
    video_label: str,
    plan: dict[str, Any] | None,
    *,
    render_w: int,
    render_h: int,
) -> tuple[list[str], str]:
    if not hyperframes.is_hyperframes_plan(plan):
        return [], video_label
    parts: list[str] = []
    current_video = video_label
    font_name = _escape_drawtext_value(get_settings().subtitle_font)
    text_elements = [
        dict(element)
        for element in list(plan.get("elements") or [])
        if isinstance(element, dict) and element.get("kind") == "text" and str(element.get("track") or "") == "subtitle_emphasis"
    ]
    for index, element in enumerate(text_elements):
        text = _escape_drawtext_value(str(element.get("text") or ""))
        if not text:
            continue
        start_time = max(0.0, float(element.get("start_sec") or 0.0))
        end_time = max(start_time + 0.4, float(element.get("end_sec") or start_time + 1.2))
        fade_duration = min(0.12, max((end_time - start_time) / 3, 0.06))
        alpha_expr = (
            f"if(lt(t\\,{start_time})\\,0\\,"
            f"if(lt(t\\,{start_time + fade_duration})\\,(t-{start_time})/{fade_duration}*0.98\\,"
            f"if(lt(t\\,{end_time - fade_duration})\\,0.98\\,"
            f"if(lt(t\\,{end_time})\\,({end_time}-t)/{fade_duration}*0.98\\,0))))"
        )
        output_label = f"vhftext{index}"
        tokens = _resolve_hyperframes_text_element_tokens(
            element,
            render_w=render_w,
            render_h=render_h,
            index=index,
        )
        parts.append(
            f"[{current_video}]drawtext="
            f"font='{font_name}':"
            f"text='{text}':"
            f"fontsize={tokens['font_size']}:"
            f"fontcolor={tokens['fontcolor']}:"
            f"alpha='{alpha_expr}':"
            f"box=1:boxcolor={tokens['boxcolor']}:boxborderw={tokens['boxborderw']}:"
            f"borderw={tokens['borderw']}:bordercolor={tokens['bordercolor']}:"
            f"shadowcolor={tokens['shadowcolor']}:shadowx={tokens['shadowx']}:shadowy={tokens['shadowy']}:"
            f"x={tokens['x_expr']}:y={tokens['y_expr']}"
            f"[{output_label}]"
        )
        current_video = output_label
    if hyperframes.progress_bar_enabled(plan):
        duration = max(0.01, float(plan.get("duration_sec") or 0.0))
        bar_h = max(34, min(48, int(render_h * 0.042)))
        margin_x = 0
        track_w = max(10, int(render_w))
        y_fill = max(0, int(render_h) - bar_h)
        bg_label = "vhfprogressbg"
        fill_src_label = "vhfprogressfillsrc"
        fill_label = "vhfprogressfill"
        fg_label = "vhfprogress"
        tick_label_prefix = "vhfprogresschaptertick"
        parts.append(
            f"[{current_video}]drawbox=x={margin_x}:y={y_fill}:w={track_w}:h={bar_h}:color=black@0.45:t=fill[{bg_label}]"
        )
        parts.append(
            f"nullsrc=s={track_w}x{bar_h}:r=30:d={duration}[{fill_src_label}]"
        )
        parts.append(
            f"[{fill_src_label}]format=rgba,"
            f"geq=r='255':g='138':b='42':a='if(lte(X\\,W*min(max(T/{duration}\\,0)\\,1))\\,235\\,0)'[{fill_label}]"
        )
        parts.append(
            f"[{bg_label}][{fill_label}]overlay=x={margin_x}:y={y_fill}:shortest=1[{fg_label}]"
        )
        current_progress_label = fg_label
        chapter_segments = hyperframes.chapter_segments(plan)
        for segment_index, segment in enumerate(chapter_segments[:10]):
            try:
                start = max(0.0, float(segment.get("start_sec", 0.0) or 0.0))
                end = min(duration, max(start, float(segment.get("end_sec", start) or start)))
            except (TypeError, ValueError):
                continue
            if end - start <= 0.1:
                continue
            x = margin_x + int(track_w * min(max(start / duration, 0.0), 1.0))
            if segment_index > 0:
                tick_label = f"{tick_label_prefix}{segment_index}"
                parts.append(
                    f"[{current_progress_label}]drawbox=x={x}:y={y_fill}:w=2:h={bar_h}:color=white@0.58:t=fill[{tick_label}]"
                )
                current_progress_label = tick_label
        for segment_index, segment in enumerate(chapter_segments[:10]):
            try:
                start = max(0.0, float(segment.get("start_sec", 0.0) or 0.0))
                end = min(duration, max(start, float(segment.get("end_sec", start) or start)))
            except (TypeError, ValueError):
                continue
            raw_title = str(segment.get("title") or "").strip()
            title = _escape_drawtext_value(raw_title)
            if not title or end - start <= 0.1:
                continue
            segment_x = margin_x + int(track_w * min(max(start / duration, 0.0), 1.0))
            segment_end_x = margin_x + int(track_w * min(max(end / duration, 0.0), 1.0))
            segment_w = max(1, segment_end_x - segment_x)
            title_pad = max(8, min(18, int(bar_h * 0.28)))
            title_font_size = _resolve_progress_title_font_size(
                raw_title,
                render_h=render_h,
                available_width=max(1, segment_w - title_pad * 2),
            )
            title_x = segment_x + title_pad
            title_y = f"{y_fill}+({bar_h}-text_h)/2"
            title_label = f"vhfprogresschaptertitle{segment_index}"
            parts.append(
                f"[{current_progress_label}]drawtext="
                f"font='{font_name}':"
                f"text='{title}':"
                f"fontsize={title_font_size}:"
                f"fontcolor=white:"
                f"borderw=2:bordercolor=black@0.55:"
                f"x={title_x}:y={title_y}"
                f"[{title_label}]"
            )
            current_progress_label = title_label
        current_video = current_progress_label
    return parts, current_video


def _resolve_hyperframes_text_element_tokens(
    element: dict[str, Any],
    *,
    render_w: int,
    render_h: int,
    index: int,
) -> dict[str, Any]:
    position = element.get("position") if isinstance(element.get("position"), dict) else {}
    center_x = int(position.get("x") or render_w * (0.62 if index % 2 == 0 else 0.38))
    center_y = int(position.get("y") or render_h * (0.16 if index % 2 == 0 else 0.22))
    style = str(element.get("style") or "").strip().lower()
    font_size = max(32, min(68, int(render_h * 0.052)))
    tokens: dict[str, Any] = {
        "font_size": font_size,
        "fontcolor": "white",
        "boxcolor": "0x111318@0.68",
        "boxborderw": max(18, int(font_size * 0.36)),
        "borderw": 3,
        "bordercolor": "0x55f0d0@0.74",
        "shadowcolor": "black@0.22",
        "shadowx": 0,
        "shadowy": 5,
        "x_expr": f"max(w*0.04\\,min(w-text_w-w*0.04\\,{center_x}-text_w/2))",
        "y_expr": f"max(h*0.08\\,min(h*0.34\\,{center_y}-text_h/2))",
    }
    if style == "social_bubble_tag":
        if index % 3 == 0:
            tokens.update({"boxcolor": "0xff4f9a@0.70", "bordercolor": "0xffffff@0.76"})
        elif index % 3 == 1:
            tokens.update({"fontcolor": "0x241607", "boxcolor": "0xfff0a6@0.80", "bordercolor": "0x55f0d0@0.78"})
        else:
            tokens.update({"boxcolor": "0x1c73ff@0.68", "bordercolor": "0xafff4d@0.74"})
    return tokens


def _resolve_delivery_resolution(
    *,
    expected_width: int,
    expected_height: int,
    delivery: dict[str, Any],
) -> tuple[int, int]:
    mode = str(delivery.get("resolution_mode") or "source").strip().lower()
    aspect_ratio = str(delivery.get("aspect_ratio") or "source").strip().lower()
    ratio = _DELIVERY_ASPECT_RATIOS.get(aspect_ratio)
    if mode != "specified":
        if ratio is None:
            return expected_width, expected_height
        ratio_w, ratio_h = ratio
        if expected_width >= expected_height:
            target_w = expected_width
            target_h = int(round(target_w * ratio_h / ratio_w))
            if target_h > expected_height:
                target_h = expected_height
                target_w = int(round(target_h * ratio_w / ratio_h))
        else:
            target_h = expected_height
            target_w = int(round(target_h * ratio_w / ratio_h))
            if target_w > expected_width:
                target_w = expected_width
                target_h = int(round(target_w * ratio_h / ratio_w))
        return max(2, target_w // 2 * 2), max(2, target_h // 2 * 2)

    preset = str(delivery.get("resolution_preset") or "1080p").strip().lower()
    target = _EXPORT_RESOLUTION_PRESETS.get(preset)
    if target is None:
        return expected_width, expected_height

    landscape_w, landscape_h = target
    if ratio is not None:
        ratio_w, ratio_h = ratio
        if ratio_h > ratio_w:
            return landscape_h, landscape_w
        if ratio_w == ratio_h:
            return landscape_h, landscape_h
        return landscape_w, int(round(landscape_w * ratio_h / ratio_w)) // 2 * 2
    if expected_height > expected_width:
        return landscape_h, landscape_w
    return landscape_w, landscape_h


def _resolve_delivery_frame_rate(*, source_fps: float, delivery: dict[str, Any]) -> float:
    mode = str(delivery.get("frame_rate_mode") or "source").strip().lower()
    if mode == "specified":
        preset = str(delivery.get("frame_rate_preset") or "30").strip()
        return _DELIVERY_FRAME_RATE_PRESETS.get(preset, 30.0)
    return max(0.0, float(source_fps or 0.0))


def _ffmpeg_fps_expr(fps: float) -> str:
    canonical = (
        (23.976, "24000/1001"),
        (24.0, "24"),
        (25.0, "25"),
        (29.97, "30000/1001"),
        (30.0, "30"),
        (50.0, "50"),
        (59.94, "60000/1001"),
        (60.0, "60"),
    )
    for target, expr in canonical:
        if abs(fps - target) < 0.05:
            return expr
    rounded = round(fps)
    if abs(fps - rounded) < 0.01 and rounded > 0:
        return str(int(rounded))
    return f"{fps:.6f}"


def _resolve_progress_title_font_size(
    title: str,
    *,
    render_h: int,
    available_width: int,
) -> int:
    base_size = max(18, min(28, int(render_h * 0.024)))
    visual_units = _drawtext_visual_units(title)
    if visual_units <= 0:
        return base_size
    fit_size = int(max(12, available_width / visual_units))
    return max(12, min(base_size, fit_size))


def _drawtext_visual_units(value: str) -> float:
    units = 0.0
    for char in str(value or ""):
        if char.isspace():
            units += 0.35
        elif ord(char) <= 0x007F:
            units += 0.58
        else:
            units += 1.0
    return units


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
    render_plan: dict[str, Any] | None = None,
    output_path: Path,
    expected_width: int,
    expected_height: int,
    debug_dir: Path | None,
    target_fps: float = 0.0,
    packaging_context: dict[str, Any] | None = None,
    packaging_assets: dict[str, Any] | None = None,
) -> Path:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        current_path = _stage_packaging_source(source_path, tmp)
        resolved_packaging_assets = (
            dict(packaging_assets)
            if isinstance(packaging_assets, dict)
            else dict(
                (
                    packaging_context if isinstance(packaging_context, dict) else _render_packaging_context(render_plan)
                ).get("assets")
                or {}
            )
        )
        insert_plan = resolved_packaging_assets.get("insert")
        if insert_plan:
            current_path = await _apply_insert_clip(
                current_path,
                insert_plan=insert_plan,
                expected_width=expected_width,
                expected_height=expected_height,
                target_fps=target_fps,
                output_path=tmp / "inserted.mp4",
                debug_dir=debug_dir,
            )
        intro_plan = resolved_packaging_assets.get("intro")
        outro_plan = resolved_packaging_assets.get("outro")
        if intro_plan or outro_plan:
            current_path = await _apply_intro_outro(
                current_path,
                intro_plan=intro_plan,
                outro_plan=outro_plan,
                expected_width=expected_width,
                expected_height=expected_height,
                target_fps=target_fps,
                output_path=tmp / "with_bookends.mp4",
                debug_dir=debug_dir,
            )
        music_plan = resolved_packaging_assets.get("music")
        watermark_plan = resolved_packaging_assets.get("watermark") or _default_dynamic_text_watermark_plan(render_plan)
        if music_plan or watermark_plan:
            current_path = await _apply_music_and_watermark(
                current_path,
                music_plan=music_plan,
                watermark_plan=watermark_plan,
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


def _resolve_packaging_media_path(value: Any) -> Path:
    return resolve_runtime_media_path(str(value or "").strip())


async def _apply_insert_clip(
    source_path: Path,
    *,
    insert_plan: dict,
    expected_width: int,
    expected_height: int,
    output_path: Path,
    debug_dir: Path | None,
    target_fps: float = 0.0,
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
    insert_source_path = _resolve_packaging_media_path(insert_plan["path"])
    insert_source_duration = _probe_duration(insert_source_path)
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
        insert_source_path,
        prepared_insert,
        expected_width=expected_width,
        expected_height=expected_height,
        target_fps=target_fps,
        trim_duration_sec=prepare_insert_duration,
        cache_dir=(debug_dir / "packaging_subcache") if debug_dir is not None else None,
    )
    insert_video_filter, insert_audio_filter = _build_insert_packaging_filter_chain(
        insert_plan=insert_plan,
        runtime_duration_sec=effective_insert_duration,
        target_fps=target_fps,
    )
    target_fps_expr = _ffmpeg_fps_expr(target_fps) if target_fps > 0 else None
    source_video_timing_filter = f",fps={target_fps_expr},settb=AVTB" if target_fps_expr else ""

    filter_parts = [
        "[0:v]split[vpre][vpost]",
        "[0:a]asplit[apre][apost]",
        f"[vpre]trim=start=0:end={insert_after_sec},setpts=PTS-STARTPTS{source_video_timing_filter}[v0]",
        f"[apre]atrim=start=0:end={insert_after_sec},asetpts=PTS-STARTPTS[a0]",
        f"[vpost]trim=start={insert_after_sec},setpts=PTS-STARTPTS{source_video_timing_filter}[v2]",
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
        *_ffmpeg_base_cmd(),
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
        *_video_delivery_encode_args(),
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
    target_fps: float = 0.0,
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
    if target_fps > 0:
        video_filters.append(f"fps={_ffmpeg_fps_expr(target_fps)}")
        video_filters.append("settb=AVTB")

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
    target_fps: float = 0.0,
) -> Path:
    prepared_paths: list[Path] = []
    if intro_plan:
        intro_prepared = output_path.with_name("intro_asset.prepared.mp4")
        await _prepare_packaging_clip(
            _resolve_packaging_media_path(intro_plan["path"]),
            intro_prepared,
            expected_width=expected_width,
            expected_height=expected_height,
            target_fps=target_fps,
            cache_dir=(debug_dir / "packaging_subcache") if debug_dir is not None else None,
        )
        prepared_paths.append(intro_prepared)

    prepared_paths.append(source_path)

    if outro_plan:
        outro_prepared = output_path.with_name("outro_asset.prepared.mp4")
        await _prepare_packaging_clip(
            _resolve_packaging_media_path(outro_plan["path"]),
            outro_prepared,
            expected_width=expected_width,
            expected_height=expected_height,
            target_fps=target_fps,
            cache_dir=(debug_dir / "packaging_subcache") if debug_dir is not None else None,
        )
        prepared_paths.append(outro_prepared)

    if len(prepared_paths) == 1:
        return source_path

    cmd = _ffmpeg_base_cmd()
    for path in prepared_paths:
        cmd.extend(["-i", str(path)])

    filter_parts: list[str] = []
    concat_inputs = ""
    target_fps_filter = f",fps={_ffmpeg_fps_expr(target_fps)},settb=AVTB" if target_fps > 0 else ""
    for index in range(len(prepared_paths)):
        segment_duration = max(
            _probe_duration(prepared_paths[index]),
            _probe_stream_duration(prepared_paths[index], "video"),
        )
        segment_duration = max(segment_duration, 0.1)
        filter_parts.append(
            f"[{index}:v]scale={expected_width}:{expected_height}:force_original_aspect_ratio=decrease,"
            f"pad={expected_width}:{expected_height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,format=yuv420p{target_fps_filter}[v{index}]"
        )
        filter_parts.append(
            f"[{index}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"aresample=async=1:first_pts=0,apad=whole_dur={segment_duration:.3f},"
            f"atrim=start=0:end={segment_duration:.3f},asetpts=N/SR/TB[a{index}]"
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
            *_video_delivery_encode_args(prefer_hardware=False, default_threads=2),
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
        raise RuntimeError(
            "ffmpeg intro/outro packaging failed: "
            f"returncode={result.returncode}; stderr_tail={result.stderr[-2000:]}"
        )
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
    watermark_plan = _normalize_watermark_plan(watermark_plan)
    if not music_plan and not watermark_plan:
        return source_path
    if music_plan and music_plan.get("path"):
        music_plan = {
            **dict(music_plan),
            "path": str(_resolve_packaging_media_path(music_plan["path"])),
            "candidate_paths": [
                str(_resolve_packaging_media_path(path))
                for path in list(music_plan.get("candidate_paths") or [])
            ],
        }
    if watermark_plan and watermark_plan.get("path"):
        watermark_plan = {
            **dict(watermark_plan),
            "path": str(_resolve_packaging_media_path(watermark_plan["path"])),
        }
    try:
        source_duration = _probe_duration(source_path)
    except Exception:
        source_duration = 0.0
    if (
        watermark_plan
        and watermark_plan.get("path")
        and await _source_already_contains_image_watermark(
            source_path,
            watermark_plan=watermark_plan,
            expected_width=expected_width,
            source_duration=source_duration,
            debug_dir=debug_dir,
        )
    ):
        watermark_plan = None
        if not music_plan:
            return source_path
    if watermark_plan and watermark_plan.get("path") and not bool(watermark_plan.get("watermark_preprocessed")):
        prepared_watermark = await _prepare_watermark_transparency_asset(
            Path(str(watermark_plan["path"])),
            output_path=output_path.with_name(f"{output_path.stem}.watermark.prepared.png"),
            expected_width=expected_width,
            watermark_plan=watermark_plan,
            debug_dir=debug_dir,
            cache_dir=(debug_dir / "packaging_subcache") if debug_dir is not None else None,
        )
        if prepared_watermark is not None:
            watermark_plan = {
                **dict(watermark_plan),
                "path": str(prepared_watermark),
                "watermark_preprocessed": True,
            }

    current_path = await _ensure_audio_duration_covers_video(
        source_path,
        output_path=output_path.with_name(f"{output_path.stem}.audio_padded{output_path.suffix}"),
        debug_dir=debug_dir,
        debug_prefix="packaging.source_audio_pad",
    )
    if music_plan:
        music_output_path = output_path if not watermark_plan else output_path.with_name(f"{output_path.stem}.music{output_path.suffix}")
        cmd = [*_ffmpeg_base_cmd(), "-i", str(current_path)]
        filter_parts: list[str] = []
        music_input_path = _resolve_packaging_media_path(music_plan["path"])
        if music_plan.get("loop_mode") == "loop_all":
            music_input_path = await _prepare_multi_track_music_loop(
                candidate_paths=[
                    _resolve_packaging_media_path(path)
                    for path in music_plan.get("candidate_paths") or [music_plan["path"]]
                ],
                output_path=output_path.with_name("music.loop_all.m4a"),
                debug_dir=debug_dir,
                cache_dir=(debug_dir / "packaging_subcache") if debug_dir is not None else None,
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
                f"[1:a]volume='{bgm_volume_expr}',highpass=f=120,lowpass=f=6000,adelay={delay_ms}|{delay_ms}"
                f"{',afade=t=in:st=' + f'{enter_sec:.3f}' + ':d=' + f'{entry_fade_sec:.3f}' if entry_fade_sec > 0 else ''}[bgm_pre]"
            )
        else:
            filter_parts.append(
                f"[1:a]volume='{bgm_volume_expr}',highpass=f=120,lowpass=f=6000"
                f"{',afade=t=in:st=0:d=' + f'{entry_fade_sec:.3f}' if entry_fade_sec > 0 else ''}[bgm_pre]"
            )
        filter_parts.append(
            "[0:a][bgm_pre]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,"
            "aformat=sample_rates=48000:channel_layouts=stereo,aresample=async=1:first_pts=0[aout]"
        )
        cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", "0:v:0", "-map", "[aout]"])
        # Re-encode here instead of copying the bookends video stream. Copying that
        # stream while filtering audio can make FFmpeg stop the mixed audio at a
        # discontinuity even though the source audio is still decodable by seek.
        cmd.extend(_video_delivery_encode_args(prefer_hardware=False, default_threads=2))
        cmd.extend(_audio_encode_args(sample_rate=48000, channels=2))
        cmd.extend(["-max_muxing_queue_size", "4096"])
        if source_duration > 0:
            cmd.extend(["-t", f"{source_duration:.6f}"])
        cmd.append(str(music_output_path))

        _write_debug_text(debug_dir, "packaging.music.ffmpeg.txt", _format_command(cmd))
        result = await _run_process(
            cmd,
            timeout=_resolve_ffmpeg_timeout(
                source_duration_sec=source_duration,
                multiplier=1.4,
                buffer_sec=360,
                minimum_timeout=900,
            ),
        )
        _write_process_debug(debug_dir, "packaging.music", result)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg music packaging failed: rc={result.returncode} stderr={result.stderr[-2000:]}")
        current_path = music_output_path
        current_path = await _ensure_audio_duration_covers_video(
            current_path,
            output_path=output_path.with_name(f"{output_path.stem}.music_audio_padded{output_path.suffix}"),
            debug_dir=debug_dir,
            debug_prefix="packaging.music_audio_pad",
        )
        try:
            source_duration = _probe_duration(current_path)
        except Exception:
            pass

    cmd = [*_ffmpeg_base_cmd(), "-i", str(current_path)]
    filter_parts = []
    video_map = "0:v:0"
    if watermark_plan and watermark_plan.get("path"):
        cmd.extend(["-loop", "1", "-i", str(watermark_plan["path"])])
        opacity = float(watermark_plan.get("opacity", 0.28) or 0.28)
        scale = float(watermark_plan.get("scale", 0.10) or 0.10)
        overlay_x, overlay_y, overlay_eval = _watermark_overlay_position(
            str(watermark_plan.get("position") or "top_right"),
            dynamic=bool(watermark_plan.get("dynamic", True)),
        )
        watermark_width = max(1, int(round(expected_width * scale)))
        watermark_filters = [f"[1:v]scale={watermark_width}:-1", "format=rgba"]
        if not bool(watermark_plan.get("watermark_preprocessed")):
            # Uploaded logo assets are often flattened onto white backgrounds; key near-white tones out at render time.
            watermark_filters.extend(
                [
                    "colorkey=0xFFFFFF:0.10:0.02",
                    "colorkey=0xF8F8F8:0.10:0.02",
                ]
            )
        watermark_filters.append(f"colorchannelmixer=aa={opacity}[wmfinal]")
        filter_parts.append(",".join(watermark_filters))
        filter_parts.append(
            f"[0:v][wmfinal]overlay=x='{overlay_x}':y='{overlay_y}':eval={overlay_eval}:format=auto:shortest=1[vout]"
        )
        video_map = "[vout]"
    elif watermark_plan and watermark_plan.get("text"):
        opacity = float(watermark_plan.get("opacity", 0.36) or 0.36)
        scale = float(watermark_plan.get("scale", 0.045) or 0.045)
        font_size = max(24, int(round(expected_height * scale)))
        text = _escape_drawtext_value(str(watermark_plan.get("text") or "RoughCut"))
        font_name = _escape_drawtext_value(get_settings().subtitle_font)
        overlay_x, overlay_y, overlay_eval = _watermark_text_position(dynamic=bool(watermark_plan.get("dynamic", True)))
        filter_parts.append(
            f"[0:v]drawtext="
            f"font='{font_name}':"
            f"text='{text}':"
            f"fontsize={font_size}:"
            f"fontcolor=white@{opacity:.3f}:"
            f"box=1:boxcolor=black@{max(0.18, min(opacity * 0.55, 0.36)):.3f}:boxborderw={max(8, int(font_size * 0.28))}:"
            f"borderw=2:bordercolor=black@{min(opacity + 0.18, 0.72):.3f}:"
            f"x='{overlay_x}':y='{overlay_y}':"
            f"alpha='if(lt(t\\,0.4)\\,t/0.4*{opacity:.3f}\\,{opacity:.3f})'"
            f"[vout]"
        )
        video_map = "[vout]"

    if not filter_parts:
        return current_path

    cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", video_map, "-map", "0:a:0"])
    cmd.extend(_video_delivery_encode_args())
    cmd.extend(_audio_encode_args(sample_rate=48000, channels=2))
    cmd.extend(["-max_muxing_queue_size", "4096"])
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
        if _resolve_video_encoder(prefer_hardware=True) != "libx264":
            with suppress(OSError):
                output_path.unlink(missing_ok=True)
            fallback_cmd = _replace_video_encode_args_for_software(cmd)
            _write_debug_text(debug_dir, "packaging.music_watermark.fallback.ffmpeg.txt", _format_command(fallback_cmd))
            fallback_result = await _run_process(
                fallback_cmd,
                timeout=_resolve_ffmpeg_timeout(
                    source_duration_sec=source_duration,
                    multiplier=3.0,
                    buffer_sec=600,
                    minimum_timeout=1200,
                ),
            )
            _write_process_debug(debug_dir, "packaging.music_watermark.fallback", fallback_result)
            if fallback_result.returncode == 0:
                return output_path
            _write_debug_text(
                debug_dir,
                "packaging.watermark_skipped.json",
                json.dumps(
                    {
                        "skipped": True,
                        "reason": "watermark_overlay_failed_after_hardware_and_software_encodes",
                        "fallback_returncode": fallback_result.returncode,
                        "hardware_returncode": result.returncode,
                        "source_path": str(current_path),
                        "output_path": str(output_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            logger.warning(
                "Skipping non-critical watermark overlay after hardware and software failures source=%s output=%s hardware_rc=%s fallback_rc=%s",
                current_path,
                output_path,
                result.returncode,
                fallback_result.returncode,
            )
            return current_path
        _write_debug_text(
            debug_dir,
            "packaging.watermark_skipped.json",
            json.dumps(
                {
                    "skipped": True,
                    "reason": "watermark_overlay_failed",
                    "returncode": result.returncode,
                    "source_path": str(current_path),
                    "output_path": str(output_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        logger.warning(
            "Skipping non-critical watermark overlay after encode failure source=%s output=%s rc=%s",
            current_path,
            output_path,
            result.returncode,
        )
        return current_path
    return output_path


def _probe_stream_duration(path: Path, codec_type: str) -> float:
    streams = _ffprobe_json(path).get("streams", [])
    durations: list[float] = []
    for stream in streams:
        if stream.get("codec_type") != codec_type:
            continue
        try:
            durations.append(float(stream.get("duration", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    return max(durations, default=0.0)


async def _ensure_audio_duration_covers_video(
    source_path: Path,
    *,
    output_path: Path,
    debug_dir: Path | None,
    debug_prefix: str,
) -> Path:
    try:
        media_info = _ffprobe_json(source_path)
        video_duration = max(
            _probe_duration(source_path),
            _probe_stream_duration(source_path, "video"),
        )
        audio_duration = _probe_stream_duration(source_path, "audio")
    except Exception:
        return source_path
    if video_duration <= 0.0:
        return source_path
    if audio_duration > 0.0 and audio_duration >= video_duration - 0.5:
        return source_path

    cmd = [*_ffmpeg_base_cmd(), "-i", str(source_path)]
    has_audio = any(stream.get("codec_type") == "audio" for stream in media_info.get("streams", []))
    if has_audio:
        filter_complex = f"[0:a]apad=whole_dur={video_duration:.3f}[aout]"
        cmd.extend(["-filter_complex", filter_complex, "-map", "0:v:0", "-map", "[aout]"])
    else:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-t",
                f"{video_duration:.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )
    cmd.extend(["-c:v", "copy", *_audio_encode_args(sample_rate=48000, channels=2), "-t", f"{video_duration:.6f}"])
    cmd.extend(["-max_muxing_queue_size", "4096", str(output_path)])
    _write_debug_text(debug_dir, f"{debug_prefix}.ffmpeg.txt", _format_command(cmd))
    result = await _run_process(
        cmd,
        timeout=_resolve_ffmpeg_timeout(
            source_duration_sec=video_duration,
            multiplier=0.6,
            buffer_sec=120,
            minimum_timeout=300,
        ),
    )
    _write_process_debug(debug_dir, debug_prefix, result)
    if result.returncode != 0 or not output_path.exists():
        logger.warning(
            "Audio duration padding failed source=%s video_duration=%.3f audio_duration=%.3f rc=%s",
            source_path,
            video_duration,
            audio_duration,
            result.returncode,
        )
        return source_path
    return output_path


async def _source_already_contains_image_watermark(
    source_path: Path,
    *,
    watermark_plan: dict,
    expected_width: int,
    source_duration: float,
    debug_dir: Path | None,
) -> bool:
    if watermark_plan.get("skip_if_present") is False:
        return False
    watermark_path = Path(str(watermark_plan.get("path") or ""))
    if source_duration <= 0.0 or not watermark_path.is_file():
        return False
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:
        _write_debug_text(
            debug_dir,
            "packaging.watermark_dedupe.json",
            json.dumps({"enabled": False, "reason": f"cv_unavailable:{type(exc).__name__}"}, ensure_ascii=False, indent=2),
        )
        return False

    template = _cv2_imread_unicode(watermark_path, cv2.IMREAD_UNCHANGED, np)
    if template is None:
        _write_debug_text(
            debug_dir,
            "packaging.watermark_dedupe.json",
            json.dumps({"enabled": False, "reason": "watermark_template_unreadable", "path": str(watermark_path)}, ensure_ascii=False, indent=2),
        )
        return False

    scale = float(watermark_plan.get("scale", 0.16) or 0.16)
    rendered_width = max(1, int(round(expected_width * scale)))
    templates = _build_watermark_match_templates(template, rendered_width=rendered_width, cv2=cv2)
    if not templates:
        return False

    threshold = float(watermark_plan.get("existing_match_threshold", 0.72) or 0.72)
    sample_times = _watermark_detection_sample_times(source_duration)
    observations: list[dict[str, Any]] = []
    matched = False
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for index, sample_time in enumerate(sample_times):
            frame_path = tmp / f"watermark_probe_{index}.png"
            result = await _run_process(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{sample_time:.3f}",
                    "-i",
                    str(source_path),
                    "-frames:v",
                    "1",
                    str(frame_path),
                ],
                timeout=60,
            )
            if result.returncode != 0 or not frame_path.is_file():
                observations.append({"time": sample_time, "status": "extract_failed"})
                continue
            frame = _cv2_imread_unicode(frame_path, cv2.IMREAD_COLOR, np)
            if frame is None:
                observations.append({"time": sample_time, "status": "frame_unreadable"})
                continue
            score, location = _best_watermark_template_score(frame, templates=templates, position=str(watermark_plan.get("position") or ""), cv2=cv2)
            observation = {"time": sample_time, "score": round(score, 4), "location": location}
            observations.append(observation)
            if score >= threshold:
                matched = True
                break

    _write_debug_text(
        debug_dir,
        "packaging.watermark_dedupe.json",
        json.dumps(
            {
                "enabled": True,
                "matched": matched,
                "threshold": threshold,
                "watermark_path": str(watermark_path),
                "observations": observations,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return matched


def _cv2_imread_unicode(path: Path, flags: int, np: Any) -> Any:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        import cv2  # type: ignore[import-not-found]

        return cv2.imdecode(data, flags)
    except Exception:
        return None


def _build_watermark_match_templates(template: Any, *, rendered_width: int, cv2: Any) -> list[Any]:
    if template is None or getattr(template, "ndim", 0) < 2:
        return []
    height, width = template.shape[:2]
    if width <= 0 or height <= 0:
        return []
    templates: list[Any] = []
    for scale_adjust in (0.92, 1.0, 1.08):
        target_width = max(8, int(round(rendered_width * scale_adjust)))
        ratio = target_width / float(width)
        target_height = max(8, int(round(height * ratio)))
        resized = cv2.resize(template, (target_width, target_height), interpolation=cv2.INTER_AREA)
        if getattr(resized, "ndim", 0) == 3 and resized.shape[2] == 4:
            resized = resized[:, :, :3]
        elif getattr(resized, "ndim", 0) == 2:
            resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        templates.append(gray)
    return templates


def _watermark_detection_sample_times(source_duration: float) -> list[float]:
    if source_duration <= 6.0:
        return [max(0.0, source_duration * 0.5)]
    last_sample = max(0.0, source_duration - 3.0)
    candidates = [
        6.0,
        30.0,
        60.0,
        90.0,
        120.0,
        180.0,
        240.0,
        source_duration * 0.35,
        source_duration * 0.50,
        source_duration * 0.75,
    ]
    sample_times: list[float] = []
    seen: set[int] = set()
    for candidate in candidates:
        sample_time = min(max(1.0, float(candidate)), last_sample)
        bucket = int(round(sample_time * 10))
        if bucket not in seen:
            seen.add(bucket)
            sample_times.append(sample_time)
    return sample_times


def _best_watermark_template_score(frame: Any, *, templates: list[Any], position: str, cv2: Any) -> tuple[float, dict[str, int]]:
    if frame is None or not templates:
        return 0.0, {"x": 0, "y": 0}
    height, width = frame.shape[:2]
    region_y0 = 0
    region_y1 = height
    normalized_position = position.lower()
    if "top" in normalized_position or not normalized_position:
        region_y1 = max(1, int(height * 0.35))
    elif "bottom" in normalized_position:
        region_y0 = max(0, int(height * 0.65))
    region = frame[region_y0:region_y1, 0:width]
    if region.size == 0:
        return 0.0, {"x": 0, "y": 0}
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    best_score = 0.0
    best_location = {"x": 0, "y": region_y0}
    for template in templates:
        template_height, template_width = template.shape[:2]
        if template_width > gray.shape[1] or template_height > gray.shape[0]:
            continue
        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_score, _, max_location = cv2.minMaxLoc(result)
        if float(max_score) > best_score:
            best_score = float(max_score)
            best_location = {"x": int(max_location[0]), "y": int(max_location[1] + region_y0)}
    return best_score, best_location


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


def _packaging_subcache_key(namespace: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        {
            "schema": "packaging_subcache_fingerprint.v1",
            "namespace": namespace,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_fingerprint_payload(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False}
    return {
        "path": str(path),
        "exists": True,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


async def _restore_packaging_subcache(
    *,
    cache_dir: Path | None,
    namespace: str,
    fingerprint: dict[str, Any],
    output_path: Path,
    extension: str,
) -> bool:
    if cache_dir is None:
        return False
    key = _packaging_subcache_key(namespace, fingerprint)
    cache_path = cache_dir / f"{namespace}.{key}{extension}"
    metadata_path = cache_dir / f"{namespace}.{key}.json"
    if not cache_path.exists() or not metadata_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if metadata.get("fingerprint") != fingerprint:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cache_path, output_path)
    return output_path.exists()


async def _store_packaging_subcache(
    *,
    cache_dir: Path | None,
    namespace: str,
    fingerprint: dict[str, Any],
    output_path: Path,
    extension: str,
) -> None:
    if cache_dir is None or not output_path.exists():
        return
    key = _packaging_subcache_key(namespace, fingerprint)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{namespace}.{key}{extension}"
    metadata_path = cache_dir / f"{namespace}.{key}.json"
    shutil.copy2(output_path, cache_path)
    metadata_path.write_text(
        json.dumps(
            {
                "schema": "packaging_subcache.v1",
                "namespace": namespace,
                "fingerprint": fingerprint,
                "path": str(cache_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def _prepare_multi_track_music_loop(
    *,
    candidate_paths: list[Path],
    output_path: Path,
    debug_dir: Path | None,
    cache_dir: Path | None = None,
) -> Path:
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in candidate_paths:
        resolved_path = resolve_runtime_media_path(path)
        key = str(resolved_path)
        if key in seen or not resolved_path.exists():
            continue
        seen.add(key)
        unique_paths.append(resolved_path)
    if not unique_paths:
        raise FileNotFoundError("No usable music tracks for loop_all mode")
    if len(unique_paths) == 1:
        return unique_paths[0]
    fingerprint = {
        "tracks": [_file_fingerprint_payload(path) for path in unique_paths],
    }
    if await _restore_packaging_subcache(
        cache_dir=cache_dir,
        namespace="music_loop",
        fingerprint=fingerprint,
        output_path=output_path,
        extension=output_path.suffix or ".m4a",
    ):
        return output_path

    cmd = _ffmpeg_base_cmd()
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
    await _store_packaging_subcache(
        cache_dir=cache_dir,
        namespace="music_loop",
        fingerprint=fingerprint,
        output_path=output_path,
        extension=output_path.suffix or ".m4a",
    )
    return output_path


async def _prepare_packaging_clip(
    source_path: Path,
    output_path: Path,
    *,
    expected_width: int,
    expected_height: int,
    target_fps: float = 0.0,
    trim_duration_sec: float | None = None,
    cache_dir: Path | None = None,
) -> Path:
    source_path = resolve_runtime_media_path(source_path)
    fingerprint = {
        "source": _file_fingerprint_payload(source_path),
        "expected_width": int(expected_width),
        "expected_height": int(expected_height),
        "target_fps": round(float(target_fps or 0.0), 6),
        "trim_duration_sec": round(float(trim_duration_sec or 0.0), 3) if trim_duration_sec is not None else None,
    }
    if await _restore_packaging_subcache(
        cache_dir=cache_dir,
        namespace="prepared_clip",
        fingerprint=fingerprint,
        output_path=output_path,
        extension=output_path.suffix or ".mp4",
    ):
        return output_path
    media_info = _ffprobe_json(source_path)
    has_audio = any(stream.get("codec_type") == "audio" for stream in media_info.get("streams", []))
    source_info = _probe_video_stream(source_path)
    duration = _probe_duration(source_path)
    video_filters = [
        *_delivery_color_filter_chain(source_info),
        f"scale={expected_width}:{expected_height}:force_original_aspect_ratio=decrease",
        f"pad={expected_width}:{expected_height}:(ow-iw)/2:(oh-ih)/2:black",
        "setsar=1",
        "format=yuv420p",
    ]
    if target_fps > 0:
        video_filters.extend([f"fps={_ffmpeg_fps_expr(target_fps)}", "settb=AVTB"])
    scale_filter = ",".join(video_filters)

    cmd = [*_ffmpeg_base_cmd(), "-i", str(source_path)]
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
            *_video_delivery_encode_args(),
            *_audio_encode_args(sample_rate=48000, channels=2),
        ]
    )
    if not has_audio:
        cmd.extend(["-map", "0:v:0", "-map", "1:a:0", "-shortest"])
    cmd.append(str(output_path))

    result = await _run_process(cmd, timeout=get_settings().ffmpeg_timeout_sec)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg packaging clip prepare failed: {result.stderr[-2000:]}")
    await _store_packaging_subcache(
        cache_dir=cache_dir,
        namespace="prepared_clip",
        fingerprint=fingerprint,
        output_path=output_path,
        extension=output_path.suffix or ".mp4",
    )
    return output_path


async def _prepare_watermark_transparency_asset(
    source_path: Path,
    *,
    output_path: Path,
    expected_width: int,
    watermark_plan: dict[str, Any],
    debug_dir: Path | None,
    cache_dir: Path | None = None,
) -> Path | None:
    if not source_path.exists():
        return None
    scale = float(watermark_plan.get("scale", 0.10) or 0.10)
    watermark_width = max(1, int(round(max(1, int(expected_width or 1)) * scale)))
    fingerprint = {
        "source": _file_fingerprint_payload(source_path),
        "watermark_width": watermark_width,
        "white_key_filters": [
            {"color": "0xFFFFFF", "similarity": 0.10, "blend": 0.02},
            {"color": "0xF8F8F8", "similarity": 0.10, "blend": 0.02},
        ],
    }
    if await _restore_packaging_subcache(
        cache_dir=cache_dir,
        namespace="watermark_rgba",
        fingerprint=fingerprint,
        output_path=output_path,
        extension=".png",
    ):
        return output_path

    cmd = [
        *_ffmpeg_base_cmd(),
        "-loop",
        "1",
        "-i",
        str(source_path),
        "-frames:v",
        "1",
        "-vf",
        (
            f"scale={watermark_width}:-1,format=rgba,"
            "colorkey=0xFFFFFF:0.10:0.02,"
            "colorkey=0xF8F8F8:0.10:0.02"
        ),
        str(output_path),
    ]
    _write_debug_text(debug_dir, "packaging.watermark_prepare.ffmpeg.txt", _format_command(cmd))
    result = await _run_process(
        cmd,
        timeout=max(30, min(int(getattr(get_settings(), "ffmpeg_timeout_sec", 600) or 600), 120)),
    )
    _write_process_debug(debug_dir, "packaging.watermark_prepare", result)
    if result.returncode != 0 or not output_path.exists():
        return None
    await _store_packaging_subcache(
        cache_dir=cache_dir,
        namespace="watermark_rgba",
        fingerprint=fingerprint,
        output_path=output_path,
        extension=".png",
    )
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
        *_ffmpeg_base_cmd(),
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


def _normalize_watermark_plan(watermark_plan: dict | None) -> dict | None:
    if not isinstance(watermark_plan, dict):
        return None
    path = str(watermark_plan.get("path") or "").strip()
    text = str(watermark_plan.get("text") or "").strip()
    if not path and not text:
        return None
    normalized = dict(watermark_plan)
    if path:
        normalized["path"] = path
    else:
        normalized.pop("path", None)
    if text:
        normalized["text"] = text[:24]
    opacity_default = 0.28 if path else 0.36
    opacity_min = 0.16 if path else 0.08
    opacity_max = 0.34 if path else 0.72
    scale_default = 0.10 if path else 0.045
    scale_min = 0.06 if path else 0.025
    scale_max = 0.12 if path else 0.09
    normalized["opacity"] = max(
        opacity_min,
        min(opacity_max, float(normalized.get("opacity", opacity_default) or opacity_default)),
    )
    normalized["scale"] = max(scale_min, min(scale_max, float(normalized.get("scale", scale_default) or scale_default)))
    normalized["position"] = str(normalized.get("position") or "top_right").strip() or "top_right"
    motion = str(normalized.get("motion") or normalized.get("watermark_motion") or "dynamic_float").strip().lower()
    normalized["motion"] = motion
    if "dynamic" not in normalized:
        normalized["dynamic"] = motion not in {"static", "fixed", "off", "none"}
    return normalized


def _default_dynamic_text_watermark_plan(render_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(render_plan, dict):
        return None
    raw_watermark = render_plan.get("watermark")
    if isinstance(raw_watermark, dict) and raw_watermark.get("enabled") is False:
        return None
    creative_profile = render_plan.get("creative_profile") if isinstance(render_plan.get("creative_profile"), dict) else {}
    content_profile = render_plan.get("content_profile") if isinstance(render_plan.get("content_profile"), dict) else {}
    text = (
        str(creative_profile.get("watermark_text") or "").strip()
        or str(content_profile.get("creator_name") or "").strip()
        or str(content_profile.get("creator_profile_name") or "").strip()
        or "RoughCut"
    )
    return {
        "text": text[:24],
        "opacity": 0.5,
        "scale": 0.052,
        "position": "top_right",
        "motion": "dynamic_float",
        "dynamic": True,
        "source": "default_text_watermark",
    }


def _watermark_overlay_position(position: str, *, dynamic: bool = False) -> tuple[str, str, str]:
    if dynamic:
        margin_x = "main_w*0.035"
        margin_y = "main_h*0.035"
        travel_x = f"(main_w-overlay_w-({margin_x})*2)"
        return (
            f"{margin_x}+{travel_x}*(0.5+0.5*sin(t*0.11))",
            f"{margin_y}+main_h*0.018*(0.5+0.5*sin(t*0.23))",
            "frame",
        )
    mapping = {
        "top_left": ("24", "24", "init"),
        "top_right": ("main_w-overlay_w-24", "24", "init"),
        "bottom_left": ("24", "main_h-overlay_h-24", "init"),
        "bottom_right": ("main_w-overlay_w-24", "main_h-overlay_h-24", "init"),
    }
    return mapping.get(position, mapping["top_right"])


def _watermark_text_position(*, dynamic: bool = False) -> tuple[str, str, str]:
    if dynamic:
        margin_x = "w*0.035"
        margin_y = "h*0.035"
        travel_x = f"(w-text_w-({margin_x})*2)"
        return (
            f"{margin_x}+{travel_x}*(0.5+0.5*sin(t*0.11))",
            f"{margin_y}+h*0.018*(0.5+0.5*sin(t*0.23))",
            "frame",
        )
    return ("w-text_w-24", "24", "init")



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
            *_ffmpeg_base_cmd(),
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
            *_ffmpeg_base_cmd(),
            "-noautorotate",
            "-i",
            str(output_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            bake_filter,
            *_video_delivery_encode_args(),
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
    safe_cmd, temp_files = _materialize_long_filter_complex_args(cmd)
    try:
        process = await asyncio.create_subprocess_exec(
            *safe_cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            with suppress(ProcessLookupError):
                process.kill()
            with suppress(Exception):
                await process.communicate()
            await close_asyncio_subprocess_transport(process)
            raise subprocess.TimeoutExpired(safe_cmd, timeout) from exc
        await close_asyncio_subprocess_transport(process)
        return subprocess.CompletedProcess(
            safe_cmd,
            int(process.returncode or 0),
            stdout=(stdout_bytes or b"").decode("utf-8", errors="replace"),
            stderr=(stderr_bytes or b"").decode("utf-8", errors="replace"),
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


def _ffmpeg_map_label(label: str) -> str:
    value = str(label or "").strip()
    if ":" in value and not value.startswith("["):
        return value
    if value.startswith("[") and value.endswith("]"):
        return value
    return f"[{value}]"


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
    fps = _parse_frame_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
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
        "codec_name": stream.get("codec_name", ""),
        "pix_fmt": stream.get("pix_fmt", ""),
        "color_range": stream.get("color_range", ""),
        "color_space": stream.get("color_space", ""),
        "color_transfer": stream.get("color_transfer", ""),
        "color_primaries": stream.get("color_primaries", ""),
        "fps": fps,
        "display_width": display_width,
        "display_height": display_height,
        "rotation_raw": rotation_raw,
        "rotation_cw": rotation_cw,
        "has_display_matrix": has_display_matrix,
        "tags": stream.get("tags", {}),
    }


def _parse_frame_rate(value: Any) -> float:
    text = str(value or "0/1").strip()
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            denominator_value = float(denominator)
            return float(numerator) / denominator_value if denominator_value else 0.0
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


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

