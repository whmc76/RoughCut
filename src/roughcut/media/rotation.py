"""
Video orientation detection.

Strategy:
1. Extract a raw frame (with -noautorotate) from the video.
2. Ask the vision model whether the image looks correctly oriented.
   The vision model sees the ACTUAL CONTENT, which is the ground truth.
3. Fall back to Display Matrix metadata only when the vision model
   is unavailable (no Ollama/OpenAI configured).

Why vision-first: iPhone HEVC recordings can have an incorrect Display
Matrix (-90°) even for landscape content, which would cause wrong rotation
if metadata is used as the primary source.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from roughcut.config import get_settings
from roughcut.providers.multimodal import complete_with_images


async def detect_video_rotation(source_path: Path) -> int:
    """
    Return the clockwise rotation (0 / 90 / 180 / 270) needed to display
    the video right-side up.

    Vision model is the primary source — it sees the actual pixel content.
    Falls back to Display Matrix metadata when vision is unavailable.
    Returns 0 on any failure.
    """
    settings = get_settings()
    duration = _probe_duration(source_path)
    if duration <= 0:
        return 0

    with tempfile.TemporaryDirectory() as tmpdir:
        frames = _extract_raw_frames(source_path, duration, Path(tmpdir), count=1)
        if not frames:
            return _rotation_from_metadata(source_path)

        try:
            answer = await complete_with_images(
                _ROTATION_PROMPT,
                frames,
                max_tokens=30,
                temperature=0,
                json_mode=False,
            )
            return _parse_rotation(answer)
        except Exception:
            return _rotation_from_metadata(source_path)


# ── Frame extraction ──────────────────────────────────────────────────────────

def _probe_duration(source_path: Path) -> float:
    try:
        import json as _json
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(source_path)],
            capture_output=True, timeout=10,
        )
        data = _json.loads(r.stdout.decode("utf-8", errors="replace"))
        return float(data.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def _extract_raw_frames(
    source_path: Path,
    duration: float,
    tmpdir: Path,
    count: int = 1,
) -> list[Path]:
    """
    Extract frames WITHOUT any rotation correction at evenly spaced positions.
    These are the raw encoded pixels, letting the vision model see the true content.
    """
    frames: list[Path] = []
    for i in range(count):
        seek = duration * (i + 1) / (count + 1)
        out = tmpdir / f"frame_{i:02d}.jpg"
        r = subprocess.run(
            [
                "ffmpeg", "-y",
                "-noautorotate",
                "-ss", f"{seek:.2f}",
                "-i", str(source_path),
                "-frames:v", "1",
                "-update", "1",
                "-q:v", "3",
                "-vf", "scale=960:-2",   # larger frame = more detail for model
                str(out),
            ],
            capture_output=True,
            timeout=20,
        )
        if r.returncode == 0 and out.exists():
            frames.append(out)
    return frames


# ── Vision model ──────────────────────────────────────────────────────────────

_ROTATION_PROMPT = (
    "Look at this image. Can you read the text normally (left to right)? "
    "Are people/objects right-side up? Is this a correctly oriented photograph?\n\n"
    "Answer with ONLY a single number: 0 (correct as-is), 90, 180, or 270 "
    "(degrees clockwise to rotate). No other text."
)


# ── Metadata fallback ─────────────────────────────────────────────────────────

def _rotation_from_metadata(source_path: Path) -> int:
    """
    Read clockwise rotation from Display Matrix side-data or 'rotate' tag.
    Used only as fallback when no vision model is available.

    Display Matrix 'rotation' in ffprobe = degrees to apply for correct display.
    e.g. rotation=-90 → apply -90° (CCW) → normalize to 270° CW.
    """
    try:
        import json as _json
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(source_path)],
            capture_output=True, timeout=10,
        )
        data = _json.loads(r.stdout.decode("utf-8", errors="replace"))
        for stream in data.get("streams", []):
            if stream.get("codec_type") != "video":
                continue
            for sd in stream.get("side_data_list", []):
                if "rotation" in sd:
                    raw = int(sd["rotation"])  # -90 → 270° CW
                    return int(raw % 360)
            rot_tag = stream.get("tags", {}).get("rotate", "0")
            rot = int(rot_tag)
            if rot != 0:
                return int(rot % 360)
    except Exception:
        pass
    return 0


def _parse_rotation(text: str) -> int:
    """Extract rotation value from LLM response."""
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    for valid in (270, 180, 90, 0):
        if str(valid) in text:
            return valid
    return 0
