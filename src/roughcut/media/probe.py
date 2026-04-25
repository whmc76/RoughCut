from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from roughcut.config import get_settings


@dataclass
class MediaMeta:
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    audio_sample_rate: int
    audio_channels: int
    file_size: int
    format_name: str
    bit_rate: int


async def probe(path: Path) -> MediaMeta:
    """Run ffprobe on the given file and return metadata."""
    settings = get_settings()
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=settings.ffmpeg_timeout_sec),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)
    fmt = data.get("format", {})

    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})

    fps = 0.0
    fps_str = video_stream.get("r_frame_rate", "0/1")
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0.0

    return MediaMeta(
        duration=float(fmt.get("duration", 0)),
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=fps,
        video_codec=video_stream.get("codec_name", ""),
        audio_codec=audio_stream.get("codec_name", ""),
        audio_sample_rate=int(audio_stream.get("sample_rate", 0)),
        audio_channels=int(audio_stream.get("channels", 0)),
        file_size=int(fmt.get("size", 0)),
        format_name=fmt.get("format_name", ""),
        bit_rate=int(fmt.get("bit_rate", 0)),
    )


def validate_media(meta: MediaMeta) -> None:
    """Raise ValueError if media doesn't meet requirements."""
    settings = get_settings()
    if meta.duration > settings.max_video_duration_sec:
        raise ValueError(
            f"Video duration {meta.duration:.0f}s exceeds limit of {settings.max_video_duration_sec}s"
        )
