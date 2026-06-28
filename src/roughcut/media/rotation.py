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
from hashlib import sha256
from pathlib import Path

from roughcut.config import get_settings
from roughcut.providers.multimodal import complete_with_images

_VALID_ROTATIONS = {0, 90, 180, 270}
_VISION_FRAME_COUNT = 3
_VISION_CONFIDENCE_THRESHOLD = 0.62
_VISION_STRONG_CONFIDENCE_THRESHOLD = 0.8
_ROTATION_FILTERS = {
    90: ("transpose=1",),
    180: ("hflip", "vflip"),
    270: ("transpose=2",),
}
_ORIENTATION_DECISION_CACHE_DIR = Path("data") / "runtime" / "orientation_decisions"
_ORIENTATION_DECISION_CACHE_VERSION = "pov-v3"


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


def normalize_rotation_payload(payload: dict[str, object] | object | None) -> dict[str, object]:
    if payload is None:
        payload_dict: dict[str, object] = {}
    elif isinstance(payload, RotationDecision):
        payload_dict = payload.to_dict()
    elif isinstance(payload, dict):
        payload_dict = dict(payload)
    elif hasattr(payload, "to_dict"):
        try:
            maybe_payload = payload.to_dict()
            payload_dict = dict(maybe_payload) if isinstance(maybe_payload, dict) else {}
        except Exception:
            payload_dict = {}
    else:
        payload_dict = {}

    try:
        raw_rotation = int(float(payload_dict.get("rotation_cw") or payload_dict.get("rotation") or 0))
    except Exception:
        raw_rotation = 0
    normalized_rotation = raw_rotation % 360
    rotation_cw = min(
        _VALID_ROTATIONS,
        key=lambda value: min(abs(value - normalized_rotation), 360 - abs(value - normalized_rotation)),
    )
    return {
        "rotation_cw": int(rotation_cw),
        "source": str(payload_dict.get("source") or "").strip(),
        "confidence": _safe_confidence(payload_dict.get("confidence")),
        "reason": str(payload_dict.get("reason") or "").strip(),
        "metadata_rotation_cw": _safe_int(payload_dict.get("metadata_rotation_cw"), 0) % 360,
    }


def build_orientation_video_filter(
    orientation_decision: dict[str, object] | object | None,
    *extra_filters: str,
) -> str:
    """
    Build an ffmpeg filter chain that uses RoughCut's visual orientation decision.

    Callers should pair this with ``-noautorotate`` so ffmpeg does not apply
    source Display Matrix metadata before these explicit filters run.
    """
    rotation_cw = int(normalize_rotation_payload(orientation_decision).get("rotation_cw") or 0)
    filters = [*_ROTATION_FILTERS.get(rotation_cw, ()), "sidedata=mode=delete:type=DISPLAYMATRIX"]
    filters.extend(filter(None, (str(item or "").strip() for item in extra_filters)))
    return ",".join(filters)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _safe_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except Exception:
        confidence = 0.0
    return max(0.0, min(1.0, confidence))


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

    metadata_summary = _probe_rotation_metadata_summary(source_path)
    metadata_rotation = int(metadata_summary.get("rotation_cw") or 0)
    if metadata_rotation == 0 and not bool(metadata_summary.get("has_display_matrix")):
        return RotationDecision(
            rotation_cw=0,
            source="metadata_zero",
            confidence=0.92,
            reason="Source metadata already reports upright orientation",
            metadata_rotation_cw=0,
        )
    cached_decision = _read_cached_orientation_decision(source_path, metadata_rotation=metadata_rotation)
    if cached_decision is not None:
        return cached_decision

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
            vision_frames = _build_orientation_candidate_sheets(frames, Path(tmpdir)) or frames
            answer = await complete_with_images(
                _ROTATION_PROMPT,
                vision_frames,
                max_tokens=120,
                temperature=0,
                json_mode=True,
            )
            vision = _parse_vision_rotation(answer)
            vision = _guard_weak_pov_180_decision(
                vision,
                source_path=source_path,
                metadata_rotation=metadata_rotation,
            )
            decision = _resolve_rotation_decision(
                vision=vision,
                metadata_rotation=metadata_rotation,
                frame_count=len(frames),
            )
            _write_cached_orientation_decision(source_path, decision)
            return decision
        except Exception:
            return RotationDecision(
                rotation_cw=metadata_rotation,
                source="metadata",
                confidence=0.55 if metadata_rotation else 0.25,
                reason="Visual orientation detection failed; using source rotation metadata",
                metadata_rotation_cw=metadata_rotation,
                frame_count=len(frames),
            )


def _read_cached_orientation_decision(
    source_path: Path,
    *,
    metadata_rotation: int,
) -> RotationDecision | None:
    cache_path = _orientation_decision_cache_path(source_path)
    if cache_path is None or not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    normalized = normalize_rotation_payload(payload)
    confidence = _safe_confidence(payload.get("confidence") if isinstance(payload, dict) else None)
    if confidence < _VISION_CONFIDENCE_THRESHOLD:
        return None
    if str(payload.get("cache_version") or "") != _ORIENTATION_DECISION_CACHE_VERSION:
        return None
    source = str(payload.get("source") or "") if isinstance(payload, dict) else ""
    if source not in {"vision", "vision_metadata_agree", "vision_cache"}:
        return None
    return RotationDecision(
        rotation_cw=int(normalized["rotation_cw"]),
        source="vision_cache",
        confidence=confidence,
        reason=str(payload.get("reason") or "Cached visual orientation decision").strip()[:240],
        metadata_rotation_cw=int(metadata_rotation or 0) % 360,
        frame_count=_safe_int(payload.get("frame_count"), 0) if isinstance(payload, dict) else 0,
        raw_answer=str(payload.get("raw_answer") or "")[:1000] if isinstance(payload, dict) else "",
    )


def _write_cached_orientation_decision(source_path: Path, decision: RotationDecision) -> None:
    if decision.source not in {"vision", "vision_metadata_agree"}:
        return
    if decision.confidence < _VISION_CONFIDENCE_THRESHOLD:
        return
    cache_path = _orientation_decision_cache_path(source_path)
    if cache_path is None:
        return
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_payload = {
            **decision.to_dict(),
            "cache_version": _ORIENTATION_DECISION_CACHE_VERSION,
        }
        cache_path.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _orientation_decision_cache_path(source_path: Path) -> Path | None:
    fingerprint = _source_orientation_fingerprint(source_path)
    if not fingerprint:
        return None
    return _ORIENTATION_DECISION_CACHE_DIR / f"{fingerprint}.json"


def _source_orientation_fingerprint(source_path: Path) -> str:
    try:
        stat = source_path.stat()
    except OSError:
        return ""
    digest = sha256()
    digest.update(str(source_path.name).encode("utf-8", errors="replace"))
    digest.update(str(int(stat.st_size)).encode("ascii"))
    try:
        with source_path.open("rb") as handle:
            head = handle.read(1024 * 1024)
            digest.update(head)
            if stat.st_size > 1024 * 1024:
                handle.seek(max(0, stat.st_size - 1024 * 1024))
                digest.update(handle.read(1024 * 1024))
    except OSError:
        return ""
    return digest.hexdigest()[:24]


def _guard_weak_pov_180_decision(
    vision: _VisionRotation,
    *,
    source_path: Path,
    metadata_rotation: int,
) -> _VisionRotation:
    if vision.rotation_cw != 180:
        return vision
    if vision.confidence >= 0.9:
        return vision
    if int(metadata_rotation or 0) % 360 not in {90, 270}:
        return vision
    width, height = _probe_encoded_video_dimensions(source_path)
    if width <= height:
        return vision
    guarded_reason = (
        "POV guard kept the raw landscape top/bottom relationship: the model chose "
        "180 degrees below high confidence, while the encoded frames are already "
        "landscape and the source metadata only suggests a 90/270 portrait transform."
    )
    return _VisionRotation(
        rotation_cw=0,
        confidence=max(_VISION_CONFIDENCE_THRESHOLD, min(0.78, vision.confidence - 0.05)),
        reason=guarded_reason,
        raw_answer=vision.raw_answer,
    )


def _probe_encoded_video_dimensions(source_path: Path) -> tuple[int, int]:
    try:
        import json as _json
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                str(source_path),
            ],
            capture_output=True,
            timeout=10,
        )
        data = _json.loads(r.stdout.decode("utf-8", errors="replace"))
        stream = (data.get("streams") or [{}])[0]
        return int(stream.get("width") or 0), int(stream.get("height") or 0)
    except Exception:
        return 0, 0


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
    "You are choosing the correct display orientation for a video. Each attached "
    "image is a contact sheet made from one raw video frame without metadata "
    "autorotation. The four labeled panels show candidate clockwise rotations: "
    "0, 90, 180, and 270. Choose the single rotation label whose panel looks most "
    "naturally upright across the sheets. The goal is not merely landscape versus "
    "portrait; the goal is the viewer's natural orientation for the recorded scene. "
    "For first-person tabletop/product/unboxing footage without an on-camera person, "
    "use the operator POV as the primary target: the operator is below/behind the "
    "camera, hands and forearms usually enter from the lower edge, the product or "
    "box sits in the middle/far side of the table, and fixed packaging, desk mat, "
    "or background text is easiest to read in the correct direction. A top-down "
    "table scene can still look plausible after a 180-degree turn, so never choose "
    "0 over 180 only because both are landscape or both show a horizontal tabletop. "
    "For POV footage, choose 180 only when the 180 panel itself unmistakably "
    "preserves the operator POV, especially hands or forearms entering from the "
    "lower edge; otherwise prefer the raw landscape top/bottom relationship. "
    "Use gravity cues, room structure, faces, hands, readable fixed text, and the "
    "global top/bottom relationship of the whole scene. Ignore logos, labels, "
    "stickers, or text printed on objects actively held or rotated by hand because "
    "those objects can be turned independently inside a correctly oriented video. "
    "Do not choose a portrait rotation merely because the file metadata may say "
    "portrait.\n\n"
    'Return JSON only: {"rotation":0,"confidence":0.0,"reason":""}\n'
    "rotation must be one of 0, 90, 180, 270. Use confidence >= 0.7 only when the "
    "best panel is clearly more natural than the others. In the reason, name the "
    "specific visual evidence used for the chosen top/bottom orientation."
)


def _build_orientation_candidate_sheets(frames: list[Path], tmpdir: Path) -> list[Path]:
    try:
        from PIL import Image, ImageDraw, ImageOps
    except Exception:
        return []

    sheets: list[Path] = []
    cell_w = 480
    cell_h = 300
    label_h = 34
    rotations = (0, 90, 180, 270)
    for index, frame in enumerate(frames):
        try:
            with Image.open(frame) as source:
                source = ImageOps.exif_transpose(source).convert("RGB")
                sheet = Image.new("RGB", (cell_w * 2, (cell_h + label_h) * 2), "white")
                draw = ImageDraw.Draw(sheet)
                for panel_index, rotation in enumerate(rotations):
                    candidate = source.rotate(-rotation, expand=True)
                    candidate.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
                    x = (panel_index % 2) * cell_w
                    y = (panel_index // 2) * (cell_h + label_h)
                    draw.rectangle([x, y, x + cell_w - 1, y + label_h - 1], fill=(20, 20, 20))
                    draw.text((x + 12, y + 9), f"ROTATION {rotation} CW", fill=(255, 255, 255))
                    paste_x = x + (cell_w - candidate.width) // 2
                    paste_y = y + label_h + (cell_h - candidate.height) // 2
                    sheet.paste(candidate, (paste_x, paste_y))
                out = tmpdir / f"orientation_candidates_{index:02d}.jpg"
                sheet.save(out, quality=88)
                sheets.append(out)
        except Exception:
            continue
    return sheets


# ── Metadata fallback ─────────────────────────────────────────────────────────

def _rotation_from_metadata(source_path: Path) -> int:
    return int(_probe_rotation_metadata_summary(source_path).get("rotation_cw") or 0)


def _probe_rotation_metadata_summary(source_path: Path) -> dict[str, object]:
    """
    Read clockwise rotation from Display Matrix side-data or 'rotate' tag.
    Used only as fallback when no vision model is available.

    Display Matrix 'rotation' in ffprobe = degrees to apply for correct display.
    e.g. rotation=-90 → apply -90° (CCW) → normalize to 270° CW.
    """
    summary = {
        "rotation_cw": 0,
        "has_display_matrix": False,
    }
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
                if sd.get("side_data_type") == "Display Matrix":
                    summary["has_display_matrix"] = True
                if "rotation" in sd:
                    raw = int(sd["rotation"])  # -90 → 270° CW
                    summary["rotation_cw"] = int(raw % 360)
                    return summary
            rot_tag = stream.get("tags", {}).get("rotate", "0")
            rot = int(rot_tag)
            if rot != 0:
                summary["rotation_cw"] = int(rot % 360)
                return summary
    except Exception:
        return summary
    return summary


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
