from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from roughcut.remix.contracts import SceneSpan
from roughcut.remix.scene_index import match_clip_to_scene


EDIT_PLAN_SCHEMA = "roughcut.remix.edit_plan.v1"
DEFAULT_SELECTION_BASIS = "source_asr_topic_anchor_with_min_gap"


def build_edit_plan_payload(
    *,
    episode: int,
    title: str,
    source_video: str | Path,
    topic_plan_path: str | Path,
    scene_index_path: str | Path,
    source_asr_index_path: str | None,
    narration_path: str | Path,
    subtitle_path: str | Path,
    montage_path: str | Path,
    output_path: str | Path,
    clip_starts: Sequence[float],
    clip_durations: Sequence[float],
    segment_paths: Sequence[str | Path | None],
    scene_spans: Sequence[SceneSpan],
    video_transform: dict[str, Any],
    selection_basis: str = DEFAULT_SELECTION_BASIS,
) -> dict[str, Any]:
    clips = build_clip_entries(
        episode=episode,
        clip_starts=clip_starts,
        clip_durations=clip_durations,
        segment_paths=segment_paths,
        scene_spans=scene_spans,
        selection_basis=selection_basis,
    )
    return {
        "schema": EDIT_PLAN_SCHEMA,
        "episode": int(episode),
        "title": title,
        "source_video": str(source_video),
        "topic_plan_path": str(topic_plan_path),
        "scene_index_path": str(scene_index_path),
        "source_asr_index_path": source_asr_index_path,
        "narration_path": str(narration_path),
        "subtitle_path": str(subtitle_path),
        "montage_path": str(montage_path),
        "output_path": str(output_path),
        "video_transform": dict(video_transform),
        "clip_count": len(clips),
        "clips": clips,
    }


def build_clip_entries(
    *,
    episode: int,
    clip_starts: Sequence[float],
    clip_durations: Sequence[float],
    segment_paths: Sequence[str | Path | None],
    scene_spans: Sequence[SceneSpan],
    selection_basis: str = DEFAULT_SELECTION_BASIS,
) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    for index, start in enumerate(clip_starts):
        duration = float(clip_durations[index]) if index < len(clip_durations) else 0.0
        segment_path = segment_paths[index] if index < len(segment_paths) else None
        clips.append(
            {
                "clip_id": f"s02e{int(episode):02d}_clip_{index + 1:02d}",
                "source_start_sec": round(float(start), 3),
                "source_end_sec": round(float(start) + duration, 3),
                "duration_sec": round(duration, 3),
                "segment_path": str(segment_path) if segment_path else None,
                "selection_basis": selection_basis,
                "scene_match": match_clip_to_scene(
                    clip_start_sec=float(start),
                    clip_duration_sec=duration,
                    scenes=list(scene_spans),
                ),
            }
        )
    return clips
