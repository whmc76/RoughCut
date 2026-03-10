from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from fastcut.config import get_settings


async def render_video(
    source_path: Path,
    render_plan: dict,
    editorial_timeline: dict,
    output_path: Path,
    subtitle_items: list[dict] | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    """
    Render video according to editorial_timeline and render_plan.

    editorial_timeline.segments: [{start, end, type: keep|remove, reason}]
    render_plan: {loudness, voice_processing, subtitles, ...}
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()

    # Build ffmpeg filter complex for trimming
    keep_segments = [s for s in editorial_timeline.get("segments", []) if s.get("type") == "keep"]

    if not keep_segments:
        raise ValueError("No keep segments in editorial timeline")

    # Build concat filter
    filter_parts: list[str] = []
    inputs: list[str] = []

    for i, seg in enumerate(keep_segments):
        start = seg["start"]
        end = seg["end"]
        filter_parts.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];")
        filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];")
        inputs.append(f"[v{i}][a{i}]")

    n = len(keep_segments)
    concat_filter = "".join(filter_parts)
    concat_filter += f"{''.join(inputs)}concat=n={n}:v=1:a=1[vout][aout]"

    # Voice processing
    vp = render_plan.get("voice_processing", {})
    audio_filter = "[aout]"
    if vp.get("noise_reduction"):
        audio_filter += "anlmdn,"
    audio_filter += "loudnorm=I=-14:TP=-1:LRA=11[afinal]"

    filter_complex = concat_filter + ";" + audio_filter

    # Subtitle filter
    if subtitle_items and render_plan.get("subtitles"):
        srt_path = _write_srt(subtitle_items, output_path.parent / "subtitles.srt")
        filter_complex += f";[vout]subtitles={srt_path}[vfinal]"
        video_map = "[vfinal]"
    else:
        video_map = "[vout]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(source_path),
        "-filter_complex", filter_complex,
        "-map", video_map,
        "-map", "[afinal]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path),
    ]

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.ffmpeg_timeout_sec,
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg render failed: {result.stderr[-2000:]}")

    return output_path


def _write_srt(subtitle_items: list[dict], srt_path: Path) -> Path:
    """Write subtitle_items to SRT file format."""
    lines: list[str] = []
    for i, item in enumerate(subtitle_items, 1):
        start = _srt_time(item["start_time"])
        end = _srt_time(item["end_time"])
        text = item.get("text_final") or item.get("text_norm") or item.get("text_raw", "")
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")

    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return srt_path


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
