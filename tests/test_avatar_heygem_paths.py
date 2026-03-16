from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.avatar.runtime import _stage_video_for_heygem
from roughcut.providers.avatar.heygem import (
    HeyGemAvatarProvider,
    _resolve_presenter_source,
    _resolve_task_timeout_seconds,
)


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
    monkeypatch.setattr(
        heygem_mod,
        "_prepare_presenter_video",
        lambda *, local_path, shared_video_dir: shared_video_dir / f"{local_path.stem}_heygem_anchor.mp4",
    )

    source = tmp_path / "presenter.mp4"
    source.write_bytes(b"video")

    presenter_source = _resolve_presenter_source(str(source))

    assert presenter_source == "/code/data/inputs/video/presenter_heygem_anchor.mp4"


def test_heygem_poll_task_surfaces_non_success_code():
    provider = HeyGemAvatarProvider()

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 10004, "msg": "任务不存在", "data": {}}

    class FakeClient:
        def get(self, url: str, headers: dict[str, str], params: dict[str, object]):
            assert url.endswith("/easy/query")
            assert params["code"] == "task-1"
            return FakeResponse()

    with pytest.raises(RuntimeError, match="任务不存在"):
        provider._poll_task(
            client=FakeClient(),
            headers={},
            query_endpoint="http://127.0.0.1:49202/easy/query",
            task_code="task-1",
        )


def test_heygem_poll_task_treats_missing_task_as_success_when_result_file_exists(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    provider = HeyGemAvatarProvider()
    shared_root = tmp_path / "heygem"
    (shared_root / "temp" / "task-1-r.mp4").parent.mkdir(parents=True, exist_ok=True)
    (shared_root / "temp" / "task-1-r.mp4").write_bytes(b"video")
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 10004, "msg": "任务不存在", "data": {}}

    class FakeClient:
        def get(self, url: str, headers: dict[str, str], params: dict[str, object]):
            assert url.endswith("/easy/query")
            assert params["code"] == "task-1"
            return FakeResponse()

    payload = provider._poll_task(
        client=FakeClient(),
        headers={},
        query_endpoint="http://127.0.0.1:49202/easy/query",
        task_code="task-1",
    )

    assert payload["code"] == 10000
    assert payload["data"]["status"] == 2
    assert payload["data"]["result"] == "/task-1-r.mp4"


def test_heygem_execute_segment_does_not_fallback_to_wrong_submit_endpoint_after_task_starts(monkeypatch):
    provider = HeyGemAvatarProvider()
    calls: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def post(self, url: str, headers: dict[str, str], json: dict[str, object]):
            calls.append(url)
            assert url.endswith("/easy/submit")
            return FakeResponse({"code": 10000, "msg": "ok"})

    def fake_poll_task(**kwargs):
        raise RuntimeError("任务不存在")

    monkeypatch.setattr(provider, "_poll_task", fake_poll_task)

    with pytest.raises(RuntimeError, match="heygem task failed from .*?/easy/submit->.*?/easy/query: 任务不存在"):
        provider._execute_segment(
            client=FakeClient(),
            headers={},
            request={"submit_endpoint": "http://127.0.0.1:49202/easy/submit"},
            presenter_source="/code/data/inputs/video/presenter.mp4",
            segment={"segment_id": "avatar_full_track", "audio_url": "/code/data/inputs/audio/drive.wav"},
        )

    assert calls == ["http://127.0.0.1:49202/easy/submit"]


def test_resolve_task_timeout_seconds_scales_for_long_audio():
    assert _resolve_task_timeout_seconds({"duration_sec": 30}) == 600.0
    assert _resolve_task_timeout_seconds({"duration_sec": 300}) == 1080.0
    assert _resolve_task_timeout_seconds({"duration_sec": 2000}) == 3600.0
