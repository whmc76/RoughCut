from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


REVIEW_FRAMES_SCHEMA = "roughcut.remix.review_frames.v1"


def review_frame_timestamps(duration_sec: float, *, min_count: int = 5) -> list[float]:
    duration = max(0.0, float(duration_sec))
    if duration <= 0.0:
        return []
    if min_count <= 1:
        return [round(min(duration / 2.0, max(0.0, duration - 0.2)), 3)]
    start = min(5.0, max(0.2, duration * 0.08))
    end = max(start, duration - min(5.0, max(0.2, duration * 0.08)))
    if end <= start:
        return [round(duration / 2.0, 3)]
    return [round(start + (end - start) * index / max(1, min_count - 1), 3) for index in range(min_count)]


def build_review_frames_manifest(
    *,
    episode: int,
    title: str,
    video_path: str | Path,
    review_dir: str | Path,
    frame_paths: Sequence[str | Path],
    timestamps_sec: Sequence[float],
    crop_evidence: dict[str, Any],
) -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    for index, path in enumerate(frame_paths):
        timestamp = float(timestamps_sec[index]) if index < len(timestamps_sec) else 0.0
        frames.append(
            {
                "frame_id": f"s02e{int(episode):02d}_review_{index + 1:02d}",
                "path": str(path),
                "timestamp_sec": round(timestamp, 3),
                "purpose": "final_output_crop_caption_packaging_review",
            }
        )
    return {
        "schema": REVIEW_FRAMES_SCHEMA,
        "episode": int(episode),
        "title": title,
        "video_path": str(video_path),
        "review_dir": str(review_dir),
        "frame_count": len(frames),
        "crop_evidence": dict(crop_evidence),
        "frames": frames,
    }
