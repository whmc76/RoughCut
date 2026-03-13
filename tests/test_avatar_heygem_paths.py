from __future__ import annotations

from pathlib import Path

from roughcut.avatar.runtime import _stage_video_for_heygem
from roughcut.providers.avatar.heygem import _resolve_presenter_source


def test_stage_video_for_heygem_returns_container_video_url(tmp_path: Path, monkeypatch):
    import roughcut.avatar.runtime as runtime_mod

    shared_root = tmp_path / "face2face"
    monkeypatch.setattr(runtime_mod, "_DEFAULT_HEYGEM_ROOT", shared_root)

    source = tmp_path / "anchor.mp4"
    source.write_bytes(b"video")

    video_url = _stage_video_for_heygem(source, preview_id="preview123")

    assert video_url == "/code/data/inputs/video/preview123_anchor.mp4"
    assert (shared_root / "inputs" / "video" / "preview123_anchor.mp4").exists()


def test_resolve_presenter_source_returns_container_video_url_for_local_file(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    shared_root = tmp_path / "face2face"
    shared_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))

    source = tmp_path / "presenter.mp4"
    source.write_bytes(b"video")

    presenter_source = _resolve_presenter_source(str(source))

    assert presenter_source == "/code/data/inputs/video/presenter.mp4"
