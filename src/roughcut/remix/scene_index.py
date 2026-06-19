from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import logging
import re
import subprocess
from typing import Any

from roughcut.media.scene import detect_scenes
from roughcut.remix.contracts import SceneSpan


logger = logging.getLogger(__name__)


def detect_scene_spans(
    video_path: Path,
    *,
    source_duration_sec: float,
    threshold: float = 30.0,
    frame_skip: int = 2,
    max_runtime_sec: float | None = 180.0,
) -> tuple[str, list[SceneSpan]]:
    boundaries = detect_scenes(
        video_path,
        threshold=threshold,
        frame_skip=frame_skip,
        max_runtime_sec=max_runtime_sec,
    )
    spans = normalize_scene_spans(
        [
            SceneSpan(
                start_sec=float(item.start),
                end_sec=float(item.end),
                score=float(item.score),
                source="pyscenedetect",
            )
            for item in boundaries
        ],
        source_duration_sec=source_duration_sec,
    )
    if spans:
        return "detected", spans
    ffmpeg_spans = detect_scene_spans_with_ffmpeg(
        video_path,
        source_duration_sec=source_duration_sec,
        threshold=threshold,
        max_runtime_sec=max_runtime_sec,
    )
    if ffmpeg_spans:
        return "detected", ffmpeg_spans
    return "fallback_single_scene", [
        SceneSpan(start_sec=0.0, end_sec=round(max(0.0, source_duration_sec), 3), score=0.0, source="fallback")
    ]


def detect_scene_spans_with_ffmpeg(
    video_path: Path,
    *,
    source_duration_sec: float,
    threshold: float = 30.0,
    max_runtime_sec: float | None = 180.0,
    min_gap_sec: float = 1.0,
) -> list[SceneSpan]:
    duration = max(0.0, float(source_duration_sec))
    if duration <= 0.0:
        return []
    scene_threshold = threshold / 100.0 if threshold > 1.0 else threshold
    scene_threshold = min(1.0, max(0.05, float(scene_threshold)))
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(video_path),
        "-vf",
        f"select='gt(scene,{scene_threshold:.4f})',showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max_runtime_sec if max_runtime_sec and max_runtime_sec > 0 else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffmpeg scene fallback failed video=%s error=%s", video_path, exc)
        return []
    if result.returncode not in {0, 255}:
        logger.warning("ffmpeg scene fallback returned %s for video=%s", result.returncode, video_path)
    boundary_times = _parse_ffmpeg_scene_times(result.stderr)
    if not boundary_times:
        return []
    return _scene_spans_from_boundaries(
        boundary_times,
        source_duration_sec=duration,
        min_gap_sec=min_gap_sec,
        source="ffmpeg_scene",
    )


def _parse_ffmpeg_scene_times(stderr: str) -> list[float]:
    times: list[float] = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", stderr or ""):
        try:
            times.append(float(match.group(1)))
        except ValueError:
            continue
    return times


def _scene_spans_from_boundaries(
    boundary_times: list[float],
    *,
    source_duration_sec: float,
    min_gap_sec: float,
    source: str,
) -> list[SceneSpan]:
    duration = max(0.0, float(source_duration_sec))
    min_gap = max(0.0, float(min_gap_sec))
    boundaries: list[float] = []
    last_time = 0.0
    for boundary in sorted(set(round(item, 3) for item in boundary_times)):
        if boundary <= min_gap or boundary >= duration - min_gap:
            continue
        if boundary - last_time < min_gap:
            continue
        boundaries.append(boundary)
        last_time = boundary
    if not boundaries:
        return []
    points = [0.0, *boundaries, duration]
    spans = [
        SceneSpan(
            start_sec=points[index],
            end_sec=points[index + 1],
            score=float(index + 1),
            source=source,
        )
        for index in range(len(points) - 1)
    ]
    return normalize_scene_spans(spans, source_duration_sec=duration, min_duration_sec=min_gap)


def normalize_scene_spans(
    spans: list[SceneSpan],
    *,
    source_duration_sec: float,
    min_duration_sec: float = 0.2,
) -> list[SceneSpan]:
    normalized: list[SceneSpan] = []
    duration = max(0.0, float(source_duration_sec))
    for item in sorted(spans, key=lambda span: (span.start_sec, span.end_sec)):
        start = max(0.0, min(duration, float(item.start_sec)))
        end = max(start, min(duration, float(item.end_sec)))
        if end - start < min_duration_sec:
            continue
        if normalized and start < normalized[-1].end_sec:
            start = normalized[-1].end_sec
        if end - start < min_duration_sec:
            continue
        normalized.append(
            SceneSpan(
                start_sec=round(start, 3),
                end_sec=round(end, 3),
                score=float(item.score),
                source=item.source,
            )
        )
    return normalized


def match_clip_to_scene(
    *,
    clip_start_sec: float,
    clip_duration_sec: float,
    scenes: list[SceneSpan],
    max_snap_distance_sec: float = 2.5,
) -> dict[str, Any]:
    clip_end = clip_start_sec + max(0.0, clip_duration_sec)
    if not scenes:
        return {
            "scene_start_sec": round(clip_start_sec, 3),
            "scene_end_sec": round(clip_end, 3),
            "snap_delta_sec": 0.0,
            "match_type": "no_scene_index",
        }
    containing = [scene for scene in scenes if scene.start_sec <= clip_start_sec < scene.end_sec]
    if containing:
        scene = containing[0]
        return {
            "scene_start_sec": scene.start_sec,
            "scene_end_sec": scene.end_sec,
            "snap_delta_sec": round(clip_start_sec - scene.start_sec, 3),
            "match_type": "contains_start",
        }
    nearest = min(scenes, key=lambda scene: abs(scene.start_sec - clip_start_sec))
    delta = round(clip_start_sec - nearest.start_sec, 3)
    match_type = "nearest_start" if abs(delta) <= max_snap_distance_sec else "distant_nearest_start"
    return {
        "scene_start_sec": nearest.start_sec,
        "scene_end_sec": nearest.end_sec,
        "snap_delta_sec": delta,
        "match_type": match_type,
    }


def build_scene_index_payload(
    *,
    video_path: Path,
    source_duration_sec: float,
    status: str,
    scenes: list[SceneSpan],
    threshold: float,
    frame_skip: int,
    max_runtime_sec: float | None,
) -> dict[str, Any]:
    return {
        "schema": "roughcut.remix.scene_index.v1",
        "status": status,
        "source_video": str(video_path),
        "source_duration_sec": round(float(source_duration_sec), 3),
        "detector": {
            "provider": "pyscenedetect",
            "threshold": float(threshold),
            "frame_skip": int(frame_skip),
            "max_runtime_sec": max_runtime_sec,
        },
        "scene_count": len(scenes),
        "scenes": [asdict(scene) for scene in scenes],
    }
