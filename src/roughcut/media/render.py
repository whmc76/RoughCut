from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Callable

from roughcut.config import get_settings


logger = logging.getLogger(__name__)

_TRANSPOSE_MAP = {
    90: ",transpose=1",
    180: ",hflip,vflip",
    270: ",transpose=2",
}


async def render_video(
    source_path: Path,
    render_plan: dict,
    editorial_timeline: dict,
    output_path: Path,
    subtitle_items: list[dict] | None = None,
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)

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
    inputs: list[str] = []
    for i, seg in enumerate(keep_segments):
        start = seg["start"]
        end = seg["end"]
        filter_parts.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS"
            f"{transpose_suffix}[v{i}];"
        )
        filter_parts.append(
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];"
        )
        inputs.append(f"[v{i}][a{i}]")

    concat_filter = "".join(filter_parts)
    concat_filter += (
        f"{''.join(inputs)}concat=n={len(keep_segments)}:v=1:a=1[vtmp][aout];"
        "[vtmp]sidedata=mode=delete:type=DISPLAYMATRIX[vout]"
    )

    vp = render_plan.get("voice_processing", {})
    audio_filter = "[aout]"
    if vp.get("noise_reduction"):
        audio_filter += "anlmdn,"
    audio_filter += "loudnorm=I=-14:TP=-1:LRA=11[afinal]"

    filter_complex = concat_filter + ";" + audio_filter
    video_map = "[vout]"

    if subtitle_items and render_plan.get("subtitles"):
        from roughcut.media.subtitles import (
            escape_path_for_ffmpeg_filter,
            remap_subtitles_to_timeline,
            write_ass_file,
        )

        remapped = remap_subtitles_to_timeline(subtitle_items, keep_segments)
        if remapped:
            ass_path = output_path.parent / "subtitle.ass"
            write_ass_file(
                remapped,
                ass_path,
                font_name=settings.subtitle_font,
                font_size=settings.subtitle_font_size,
                text_color_rgb=settings.subtitle_color,
                outline_color_rgb=settings.subtitle_outline_color,
                outline_width=settings.subtitle_outline_width,
                play_res_x=expected_w,
                play_res_y=expected_h,
            )
            escaped = escape_path_for_ffmpeg_filter(ass_path)
            filter_complex += f";[vout]subtitles='{escaped}'[vfinal]"
            video_map = "[vfinal]"

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
        str(output_path),
    ]
    _write_debug_text(debug_dir, "render.ffmpeg.txt", _format_command(cmd))

    result = await _run_process(cmd, timeout=settings.ffmpeg_timeout_sec)
    _write_process_debug(debug_dir, "render", result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg render failed: {result.stderr[-2000:]}")

    await _normalize_rendered_output(
        output_path,
        expected_width=expected_w,
        expected_height=expected_h,
        debug_dir=debug_dir,
    )
    return output_path


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
                stripped.replace(output_path)
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
                baked.replace(output_path)
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
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        ),
    )


def _probe_video_stream(path: Path) -> dict[str, Any]:
    stream = next(
        (s for s in _ffprobe_json(path).get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    return _describe_stream(stream)


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
    (debug_dir / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_debug_text(debug_dir: Path | None, name: str, content: str) -> None:
    if debug_dir is None:
        return
    (debug_dir / name).write_text(content, encoding="utf-8")


def _write_process_debug(
    debug_dir: Path | None,
    prefix: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    if debug_dir is None:
        return
    (debug_dir / f"{prefix}.stdout.log").write_text(result.stdout or "", encoding="utf-8")
    (debug_dir / f"{prefix}.stderr.log").write_text(result.stderr or "", encoding="utf-8")

