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

import json
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from roughcut.config import get_settings
from roughcut.providers.multimodal import complete_with_images

_VALID_ROTATIONS = {0, 90, 180, 270}
_VISION_FRAME_COUNT = 3
_VISION_CONFIDENCE_THRESHOLD = 0.62
_VISION_STRONG_CONFIDENCE_THRESHOLD = 0.8


@dataclass(frozen=True)
class RotationDecision:
    rotation_cw: int
    source: str
    confidence: float
    reason: str = ""
    metadata_rotation_cw: int = 0
    frame_count: int = 0
    raw_answer: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _VisionRotation:
    rotation_cw: int
    confidence: float
    reason: str
    raw_answer: str


async def detect_video_rotation(source_path: Path) -> int:
    """
    Return the clockwise rotation (0 / 90 / 180 / 270) needed to display
    the video right-side up.

    Vision model is the primary source — it sees the actual pixel content.
    Falls back to Display Matrix metadata when vision is unavailable.
    Returns 0 on any failure.
    """
    return (await detect_video_rotation_decision(source_path)).rotation_cw


async def detect_video_rotation_decision(source_path: Path) -> RotationDecision:
    """
    Return a traceable rotation decision for the source video.

    Multiple raw frames are sent in one vision request so a single blurred,
    transitional, or object-only frame does not decide the whole render. The
    metadata fallback remains intentionally conservative and is used when vision
    is unavailable or low confidence.
    """
    get_settings()
    duration = _probe_duration(source_path)
    if duration <= 0:
        return RotationDecision(
            rotation_cw=0,
            source="fallback",
            confidence=0.0,
            reason="Unable to probe source duration",
        )

    metadata_rotation = _rotation_from_metadata(source_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        frames = _extract_raw_frames(source_path, duration, Path(tmpdir), count=_VISION_FRAME_COUNT)
        if not frames:
            return RotationDecision(
                rotation_cw=metadata_rotation,
                source="metadata",
                confidence=0.55 if metadata_rotation else 0.25,
                reason="No raw frames could be extracted for visual orientation detection",
                metadata_rotation_cw=metadata_rotation,
            )

        try:
            answer = await complete_with_images(
                _ROTATION_PROMPT,
                frames,
                max_tokens=120,
                temperature=0,
                json_mode=True,
            )
            vision = _parse_vision_rotation(answer)
            return _resolve_rotation_decision(
                vision=vision,
                metadata_rotation=metadata_rotation,
                frame_count=len(frames),
            )
        except Exception:
            return RotationDecision(
                rotation_cw=metadata_rotation,
                source="metadata",
                confidence=0.55 if metadata_rotation else 0.25,
                reason="Visual orientation detection failed; using source rotation metadata",
                metadata_rotation_cw=metadata_rotation,
                frame_count=len(frames),
            )


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
    safe_margin = min(max(duration * 0.08, 1.0), max(duration / 4, 0.0))
    usable_start = safe_margin if duration > safe_margin * 2 else 0.0
    usable_end = duration - safe_margin if duration > safe_margin * 2 else duration
    usable_duration = max(usable_end - usable_start, 0.1)
    for i in range(count):
        seek = usable_start + usable_duration * (i + 1) / (count + 1)
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
    "You are checking whether video frames are visually sideways or upside down. "
    "Look across all attached frames as samples from the same video. Decide the "
    "single clockwise rotation needed to make people, hands, products, objects, "
    "and readable text look naturally upright. If the angle is not obviously "
    "wrong, choose 0. Do not rotate merely because the video is portrait or "
    "landscape.\n\n"
    'Return JSON only: {"rotation":0,"confidence":0.0,"reason":""}\n'
    "rotation must be one of 0, 90, 180, 270. confidence is 0.0 to 1.0."
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
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    for valid in (270, 180, 90, 0):
        if str(valid) in text:
            return valid
    return 0


def _parse_vision_rotation(text: str) -> _VisionRotation:
    cleaned = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.DOTALL).strip()
    payload: dict[str, object] = {}
    try:
        payload = json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            try:
                payload = json.loads(match.group(0))
            except Exception:
                payload = {}

    rotation_value = payload.get("rotation", payload.get("rotation_cw"))
    try:
        rotation = int(rotation_value) % 360
    except Exception:
        rotation = _parse_rotation(cleaned)
    if rotation not in _VALID_ROTATIONS:
        rotation = 0

    try:
        confidence = float(payload.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if not payload and rotation in _VALID_ROTATIONS:
        confidence = 0.7 if rotation else 0.45

    reason = str(payload.get("reason") or "").strip()[:240]
    return _VisionRotation(
        rotation_cw=rotation,
        confidence=confidence,
        reason=reason,
        raw_answer=cleaned[:1000],
    )


def _resolve_rotation_decision(
    *,
    vision: _VisionRotation,
    metadata_rotation: int,
    frame_count: int,
) -> RotationDecision:
    metadata_rotation = int(metadata_rotation or 0) % 360
    if metadata_rotation not in _VALID_ROTATIONS:
        metadata_rotation = 0

    if vision.confidence >= _VISION_CONFIDENCE_THRESHOLD:
        return RotationDecision(
            rotation_cw=vision.rotation_cw,
            source="vision",
            confidence=vision.confidence,
            reason=vision.reason or "Vision model found a clear orientation",
            metadata_rotation_cw=metadata_rotation,
            frame_count=frame_count,
            raw_answer=vision.raw_answer,
        )

    if (
        metadata_rotation
        and vision.rotation_cw == metadata_rotation
        and vision.confidence >= 0.45
    ):
        return RotationDecision(
            rotation_cw=metadata_rotation,
            source="vision_metadata_agree",
            confidence=max(vision.confidence, 0.65),
            reason=vision.reason or "Vision and source rotation metadata agree",
            metadata_rotation_cw=metadata_rotation,
            frame_count=frame_count,
            raw_answer=vision.raw_answer,
        )

    if metadata_rotation and vision.confidence < _VISION_STRONG_CONFIDENCE_THRESHOLD:
        return RotationDecision(
            rotation_cw=metadata_rotation,
            source="metadata",
            confidence=0.55,
            reason="Vision result was low confidence; using source rotation metadata",
            metadata_rotation_cw=metadata_rotation,
            frame_count=frame_count,
            raw_answer=vision.raw_answer,
        )

    return RotationDecision(
        rotation_cw=0,
        source="none",
        confidence=max(vision.confidence, 0.25),
        reason=vision.reason or "No clearly abnormal orientation detected",
        metadata_rotation_cw=metadata_rotation,
        frame_count=frame_count,
        raw_answer=vision.raw_answer,
    )
