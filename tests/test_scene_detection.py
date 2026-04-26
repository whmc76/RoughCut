from __future__ import annotations

import sys
import time
import types
from pathlib import Path

from roughcut.media.scene import detect_scenes


class _FakeTimecode:
    def __init__(self, seconds: float) -> None:
        self._seconds = seconds

    def get_seconds(self) -> float:
        return self._seconds


class _FakeSceneManager:
    instances: list["_FakeSceneManager"] = []

    def __init__(self) -> None:
        self.frame_skip: int | None = None
        self.stopped = False
        _FakeSceneManager.instances.append(self)

    def add_detector(self, detector: object) -> None:
        self.detector = detector

    def detect_scenes(self, video: object, frame_skip: int = 0) -> int:
        self.video = video
        self.frame_skip = frame_skip
        time.sleep(0.04)
        return 10

    def stop(self) -> None:
        self.stopped = True

    def get_scene_list(self):
        return [(_FakeTimecode(1.25), _FakeTimecode(2.5))]


def _install_fake_scenedetect(monkeypatch) -> None:
    _FakeSceneManager.instances.clear()
    scenedetect = types.ModuleType("scenedetect")
    scenedetect.open_video = lambda path: {"path": path}
    scenedetect.SceneManager = _FakeSceneManager
    detectors = types.ModuleType("scenedetect.detectors")
    detectors.ContentDetector = lambda threshold=30.0: {"threshold": threshold}
    monkeypatch.setitem(sys.modules, "scenedetect", scenedetect)
    monkeypatch.setitem(sys.modules, "scenedetect.detectors", detectors)


def test_detect_scenes_passes_frame_skip(monkeypatch) -> None:
    _install_fake_scenedetect(monkeypatch)

    boundaries = detect_scenes(Path("sample.mp4"), frame_skip=3)

    assert _FakeSceneManager.instances[-1].frame_skip == 3
    assert [(item.start, item.end) for item in boundaries] == [(1.25, 2.5)]


def test_detect_scenes_stops_when_runtime_budget_expires(monkeypatch) -> None:
    _install_fake_scenedetect(monkeypatch)

    boundaries = detect_scenes(Path("sample.mp4"), max_runtime_sec=0.01)

    assert _FakeSceneManager.instances[-1].stopped is True
    assert [(item.start, item.end) for item in boundaries] == [(1.25, 2.5)]
