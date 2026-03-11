from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
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
                style_name=str((render_plan.get("subtitles") or {}).get("style") or "bold_yellow_outline"),
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
        str(base_output_path),
    ]
    _write_debug_text(debug_dir, "render.ffmpeg.txt", _format_command(cmd))

    result = await _run_process(cmd, timeout=settings.ffmpeg_timeout_sec)
    _write_process_debug(debug_dir, "render", result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg render failed: {result.stderr[-2000:]}")

    await _normalize_rendered_output(
        base_output_path,
        expected_width=expected_w,
        expected_height=expected_h,
        debug_dir=debug_dir,
    )
    if packaging_enabled:
        packaged = await _apply_packaging_plan(
            base_output_path,
            render_plan=render_plan,
            output_path=output_path,
            expected_width=expected_w,
            expected_height=expected_h,
            debug_dir=debug_dir,
        )
        await _normalize_rendered_output(
            packaged,
            expected_width=expected_w,
            expected_height=expected_h,
            debug_dir=debug_dir,
        )
    elif base_output_path != output_path:
        base_output_path.replace(output_path)
    return output_path


async def _apply_packaging_plan(
    source_path: Path,
    *,
    render_plan: dict,
    output_path: Path,
    expected_width: int,
    expected_height: int,
    debug_dir: Path | None,
) -> Path:
    current_path = source_path
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
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
                output_path=tmp / "packaged.mp4",
                debug_dir=debug_dir,
            )
        if current_path != output_path:
            current_path.replace(output_path)
    return output_path


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
    result = await _run_process(cmd, timeout=get_settings().ffmpeg_timeout_sec)
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
    result = await _run_process(cmd, timeout=get_settings().ffmpeg_timeout_sec)
    _write_process_debug(debug_dir, "packaging.bookends", result)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg intro/outro packaging failed: {result.stderr[-2000:]}")
    return output_path


async def _apply_music_and_watermark(
    source_path: Path,
    *,
    music_plan: dict | None,
    watermark_plan: dict | None,
    output_path: Path,
    debug_dir: Path | None,
) -> Path:
    if not music_plan and not watermark_plan:
        return source_path

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
        volume = float(music_plan.get("volume", 0.22) or 0.22)
        filter_parts.append(f"[{next_input_index}:a]volume={volume}[bgm]")
        filter_parts.append(
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2,"
            "loudnorm=I=-14:TP=-1:LRA=11[aout]"
        )
        audio_map = "[aout]"
        next_input_index += 1

    if watermark_plan:
        cmd.extend(["-i", str(watermark_plan["path"])])
        opacity = float(watermark_plan.get("opacity", 0.82) or 0.82)
        scale = float(watermark_plan.get("scale", 0.16) or 0.16)
        overlay_x, overlay_y = _watermark_overlay_position(str(watermark_plan.get("position") or "top_right"))
        filter_parts.append(
            f"[{next_input_index}:v][0:v]scale2ref=w=main_w*{scale}:h=-1[wm][base]"
        )
        filter_parts.append(f"[wm]format=rgba,colorchannelmixer=aa={opacity}[wmfinal]")
        filter_parts.append(f"[base][wmfinal]overlay=x={overlay_x}:y={overlay_y}:format=auto[vout]")
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
    cmd.append(str(output_path))

    _write_debug_text(debug_dir, "packaging.music_watermark.ffmpeg.txt", _format_command(cmd))
    result = await _run_process(cmd, timeout=get_settings().ffmpeg_timeout_sec)
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
    result = await _run_process(cmd, timeout=get_settings().ffmpeg_timeout_sec)
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

