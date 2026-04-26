"""Scene detection using PySceneDetect."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import threading


logger = logging.getLogger(__name__)


@dataclass
class SceneBoundary:
    start: float
    end: float
    score: float


def detect_scenes(
    video_path: Path,
    *,
    threshold: float = 30.0,
    frame_skip: int = 0,
    max_runtime_sec: float | None = None,
) -> list[SceneBoundary]:
    """Detect scene boundaries in a video file."""
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector
    except ImportError:
        raise RuntimeError("scenedetect is not installed. Run: pip install scenedetect[opencv]")

    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    timed_out = False
    timer: threading.Timer | None = None

    def _stop_detection() -> None:
        nonlocal timed_out
        timed_out = True
        scene_manager.stop()

    if max_runtime_sec is not None and max_runtime_sec > 0:
        timer = threading.Timer(float(max_runtime_sec), _stop_detection)
        timer.daemon = True
        timer.start()
    try:
        scene_manager.detect_scenes(video, frame_skip=max(0, int(frame_skip or 0)))
    finally:
        if timer is not None:
            timer.cancel()

    scene_list = scene_manager.get_scene_list()
    if timed_out:
        logger.warning(
            "Scene detection reached runtime budget; using partial boundaries video=%s max_runtime_sec=%.1f scenes=%s",
            video_path,
            float(max_runtime_sec or 0.0),
            len(scene_list),
        )
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
