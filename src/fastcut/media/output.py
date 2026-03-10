"""
Output package: MP4 + SRT + cover image — one complete set per job.
Naming: {YYYYMMDD}_{original_stem}.{ext}
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import datetime
from pathlib import Path

from fastcut.config import get_settings


def _sanitize(name: str) -> str:
    """Remove chars not safe for filenames."""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def build_output_name(source_name: str, created_at: datetime | None = None) -> str:
    """
    Build canonical output stem.
    e.g. source_name='IMG_0026.MOV', date=20260310 → '20260310_IMG_0026'
    """
    settings = get_settings()
    dt = created_at or datetime.now()
    stem = Path(source_name).stem
    pattern = settings.output_name_pattern
    name = pattern.format(date=dt.strftime("%Y%m%d"), stem=stem)
    return _sanitize(name)


def get_output_dir() -> Path:
    settings = get_settings()
    p = Path(settings.output_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


async def extract_cover_frame(
    video_path: Path,
    output_path: Path,
    *,
    seek_sec: float = 3.0,
) -> Path:
    """Extract a single frame as JPEG cover image."""
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(seek_sec),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        "-vf", "scale=1280:-2",
        str(output_path),
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=settings.ffmpeg_timeout_sec),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Cover extraction failed: {result.stderr[-500:]}")
    return output_path


def write_srt_file(subtitle_items: list[dict], output_path: Path) -> Path:
    """Write subtitle items to SRT file."""
    lines: list[str] = []
    for i, item in enumerate(subtitle_items, 1):
        start = _srt_time(item["start_time"])
        end = _srt_time(item["end_time"])
        text = item.get("text_final") or item.get("text_norm") or item.get("text_raw", "")
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    output_path.write_text("\n".join(lines), encoding="utf-8-sig")  # utf-8-sig for Windows compatibility
    return output_path


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
