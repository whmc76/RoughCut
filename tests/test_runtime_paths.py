from __future__ import annotations

from pathlib import Path

from roughcut import runtime_paths
from roughcut.runtime_paths import resolve_runtime_media_path


def test_resolve_runtime_media_path_maps_windows_data_path_to_current_project_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "RoughCut"
    expected = project_root / "data" / "runtime" / "output" / "clip.mp4"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"clip")
    monkeypatch.setattr(runtime_paths, "DEFAULT_PROJECT_ROOT", project_root)

    resolved = resolve_runtime_media_path("E:/WorkSpace/RoughCut/data/runtime/output/clip.mp4")

    assert resolved == expected


def test_resolve_runtime_media_path_strips_container_prefixed_windows_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "RoughCut"
    expected = project_root / "data" / "runtime" / "output" / "clip.mp4"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"clip")
    monkeypatch.setattr(runtime_paths, "DEFAULT_PROJECT_ROOT", project_root)

    resolved = resolve_runtime_media_path("/app/E:/WorkSpace/RoughCut/data/runtime/output/clip.mp4")

    assert resolved == expected


def test_resolve_runtime_media_path_falls_back_to_legacy_output_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "RoughCut"
    expected = project_root / "data" / "output" / "_creator_assets" / "creator" / "intro.mp4"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"clip")
    monkeypatch.setattr(runtime_paths, "DEFAULT_PROJECT_ROOT", project_root)

    resolved = resolve_runtime_media_path(
        "E:/WorkSpace/RoughCut/data/runtime/output/_creator_assets/creator/intro.mp4"
    )

    assert resolved == expected
