"""Scene detection using PySceneDetect."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SceneBoundary:
    start: float
    end: float
    score: float


def detect_scenes(video_path: Path, *, threshold: float = 30.0) -> list[SceneBoundary]:
    """Detect scene boundaries in a video file."""
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector
    except ImportError:
        raise RuntimeError("scenedetect is not installed. Run: pip install scenedetect[opencv]")

    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video)

    scene_list = scene_manager.get_scene_list()
    boundaries: list[SceneBoundary] = []
    for i, (start, end) in enumerate(scene_list):
        boundaries.append(
            SceneBoundary(
                start=start.get_seconds(),
                end=end.get_seconds(),
                score=float(i),
            )
        )
    return boundaries
