from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from roughcut.config import get_settings


async def extract_audio(video_path: Path, output_path: Path, *, sample_rate: int = 16000) -> Path:
    """Extract mono WAV audio from video file for transcription."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        str(output_path),
    ]

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.ffmpeg_timeout_sec,
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr}")

    return output_path


async def normalize_audio(input_path: Path, output_path: Path) -> Path:
    """Apply loudness normalization (EBU R128) to audio."""
    settings = get_settings()
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-filter:a", "loudnorm=I=-16:TP=-1.5:LRA=11",
        str(output_path),
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=settings.ffmpeg_timeout_sec),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalization failed: {result.stderr}")
    return output_path


async def extract_audio_clip(
    input_path: Path,
    output_path: Path,
    *,
    start_time: float,
    end_time: float,
    sample_rate: int = 16000,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.1, float(end_time) - float(start_time))
    settings = get_settings()
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(0.0, float(start_time)):.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(input_path),
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        str(output_path),
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.ffmpeg_timeout_sec,
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio clip extraction failed: {result.stderr}")
    return output_path
