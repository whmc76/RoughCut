from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.avatar.runtime import _stage_video_for_heygem
from roughcut.providers.avatar.heygem import (
    HeyGemAvatarProvider,
    _detect_shared_root,
    _resolve_audio_source,
    _resolve_local_result_path,
    _resolve_presenter_source,
    _resolve_task_timeout_seconds,
)


def _stub_missing_docker_env_file(monkeypatch, module) -> None:
    class FakeSettings:
        heygem_docker_env_file = ""

    monkeypatch.setattr(module, "get_settings", lambda: FakeSettings())


def test_stage_video_for_heygem_returns_container_video_url(tmp_path: Path, monkeypatch):
    import roughcut.avatar.runtime as runtime_mod

    shared_root = tmp_path / "face2face"
    monkeypatch.setattr(runtime_mod, "_DEFAULT_HEYGEM_ROOT", shared_root)
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))

    source = tmp_path / "anchor.mp4"
    source.write_bytes(b"video")

    video_url = _stage_video_for_heygem(source, preview_id="preview123")

    assert video_url == "/code/data/inputs/video/preview123_anchor.mp4"
    assert (shared_root / "inputs" / "video" / "preview123_anchor.mp4").exists()


def test_resolve_presenter_source_returns_container_video_url_for_local_file(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    shared_root = tmp_path / "face2face"
    shared_root.mkdir(parents=True, exist_ok=True)
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))
    monkeypatch.setattr(
        heygem_mod,
        "_prepare_presenter_video",
        lambda *, local_path, shared_video_dir: shared_video_dir / f"{local_path.stem}_heygem_anchor.mp4",
    )

    source = tmp_path / "presenter.mp4"
    source.write_bytes(b"video")

    presenter_source = _resolve_presenter_source(str(source))

    assert presenter_source == "/code/data/inputs/video/presenter_heygem_anchor.mp4"


def test_resolve_audio_source_namespaces_staged_file_by_job(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    shared_root = tmp_path / "face2face"
    shared_root.mkdir(parents=True, exist_ok=True)
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))
    monkeypatch.setattr(heygem_mod, "_probe_audio_duration_seconds", lambda path: 1.0)
    monkeypatch.setattr(heygem_mod.time, "sleep", lambda _: None)

    source = tmp_path / "drive.wav"
    source.write_bytes(b"audio")

    audio_source = _resolve_audio_source(
        str(source),
        job_id="job-123",
        segment_id="avatar_full_track",
    )

    assert audio_source == "/code/data/inputs/audio/job_123_avatar_full_track_drive.wav"
    assert (shared_root / "inputs" / "audio" / "job_123_avatar_full_track_drive.wav").exists()


def test_resolve_audio_source_prefers_host_shared_dir_when_container_root_is_unavailable(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    host_shared_root = tmp_path / "host-heygem"
    host_shared_root.mkdir(parents=True, exist_ok=True)
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", ())
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", "/code/data")
    monkeypatch.setenv("HEYGEM_SHARED_HOST_DIR", str(host_shared_root))
    monkeypatch.setattr(heygem_mod, "_probe_audio_duration_seconds", lambda path: 1.0)
    monkeypatch.setattr(heygem_mod.time, "sleep", lambda _: None)

    source = tmp_path / "drive.wav"
    source.write_bytes(b"audio")

    audio_source = _resolve_audio_source(
        str(source),
        job_id="job-123",
        segment_id="avatar_full_track",
    )

    assert audio_source == "/code/data/inputs/audio/job_123_avatar_full_track_drive.wav"
    assert (host_shared_root / "inputs" / "audio" / "job_123_avatar_full_track_drive.wav").exists()
    assert not Path("/code/data/inputs/audio/job_123_avatar_full_track_drive.wav").exists()


def test_resolve_audio_source_rejects_unreadable_staged_audio(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    shared_root = tmp_path / "face2face"
    shared_root.mkdir(parents=True, exist_ok=True)
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))
    monkeypatch.setattr(heygem_mod, "_probe_audio_duration_seconds", lambda path: None)
    monkeypatch.setattr(heygem_mod.time, "sleep", lambda _: None)

    source = tmp_path / "drive.wav"
    source.write_bytes(b"broken-audio")

    with pytest.raises(RuntimeError, match="staged_audio_unreadable"):
        _resolve_audio_source(
            str(source),
            job_id="job-123",
            segment_id="avatar_full_track",
        )


def test_detect_shared_root_prefers_docker_env_file_mount_over_default_root(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    default_root = tmp_path / "default-heygem"
    default_root.mkdir(parents=True, exist_ok=True)
    docker_root = tmp_path / "docker-heygem"
    docker_root.mkdir(parents=True, exist_ok=True)
    docker_env_file = tmp_path / "heygem.env"
    docker_env_file.write_text(f"HEYGEM_DATA_DIR={docker_root.as_posix()}\n", encoding="utf-8")

    class FakeSettings:
        heygem_docker_env_file = str(docker_env_file)

    monkeypatch.delenv("HEYGEM_SHARED_ROOT", raising=False)
    monkeypatch.delenv("HEYGEM_SHARED_HOST_DIR", raising=False)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (default_root,))
    monkeypatch.setattr(heygem_mod, "get_settings", lambda: FakeSettings())

    assert _detect_shared_root() == docker_root


def test_stage_audio_file_retries_until_final_target_is_probeable(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    shared_root = tmp_path / "face2face"
    shared_root.mkdir(parents=True, exist_ok=True)
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))
    monkeypatch.setattr(heygem_mod.time, "sleep", lambda _: None)

    source = tmp_path / "drive.wav"
    source.write_bytes(b"audio")
    target = shared_root / "inputs" / "audio" / "job_123_avatar_full_track_drive.wav"

    attempts: dict[str, int] = {"count": 0}

    def fake_probe(path: Path) -> float | None:
        attempts["count"] += 1
        return 1.0 if attempts["count"] >= 3 else None

    monkeypatch.setattr(heygem_mod, "_probe_audio_duration_seconds", fake_probe)

    audio_source = _resolve_audio_source(
        str(source),
        job_id="job-123",
        segment_id="avatar_full_track",
    )

    assert audio_source == "/code/data/inputs/audio/job_123_avatar_full_track_drive.wav"
    assert attempts["count"] >= 3
    assert target.exists()


def test_stage_audio_file_falls_back_to_ffmpeg_normalization_when_copy_is_unreadable(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    shared_root = tmp_path / "face2face"
    shared_root.mkdir(parents=True, exist_ok=True)
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))
    monkeypatch.setattr(heygem_mod.time, "sleep", lambda _: None)

    source = tmp_path / "drive.wav"
    source.write_bytes(b"audio")
    target = shared_root / "inputs" / "audio" / "job_123_avatar_seg_003_drive.wav"

    state: dict[str, bool] = {"normalized": False}

    def fake_probe(path: Path) -> float | None:
        if path == target:
            return 1.0
        if path.suffix == ".partial":
            return 1.0 if state["normalized"] else None
        return None

    def fake_normalize(*, source_path: Path, target_path: Path) -> None:
        assert source_path == source
        state["normalized"] = True
        target_path.write_bytes(b"normalized")

    monkeypatch.setattr(heygem_mod, "_probe_audio_duration_seconds", fake_probe)
    monkeypatch.setattr(heygem_mod, "_rewrite_audio_to_staged_wav", fake_normalize)

    audio_source = _resolve_audio_source(
        str(source),
        job_id="job-123",
        segment_id="avatar_seg_003",
    )

    assert audio_source == "/code/data/inputs/audio/job_123_avatar_seg_003_drive.wav"
    assert state["normalized"] is True
    assert target.exists()


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
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))

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


def test_heygem_poll_task_treats_status_one_with_result_and_100_progress_as_success():
    provider = HeyGemAvatarProvider()

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 10000,
                "msg": "",
                "data": {
                    "status": 1,
                    "progress": 100,
                    "result": "/code/data/temp/task-1/result.avi",
                },
            }

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

    assert payload["data"]["status"] == 1
    assert payload["data"]["progress"] == 100
    assert payload["data"]["result"] == "/code/data/temp/task-1/result.avi"


def test_resolve_local_result_path_maps_container_temp_path_to_shared_root(tmp_path: Path, monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    shared_root = tmp_path / "heygem"
    result_path = shared_root / "temp" / "task-1" / "result.avi"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_bytes(b"video")
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))

    resolved = _resolve_local_result_path("/code/data/temp/task-1/result.avi")

    assert resolved == str(result_path)


def test_heygem_execute_segment_treats_completed_payload_with_existing_result_as_success(monkeypatch, tmp_path: Path):
    import roughcut.providers.avatar.heygem as heygem_mod

    provider = HeyGemAvatarProvider()
    shared_root = tmp_path / "heygem"
    result_path = shared_root / "temp" / "task-1" / "result.avi"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_bytes(b"video")
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))
    monkeypatch.setattr(heygem_mod, "_resolve_audio_source", lambda *args, **kwargs: "/code/data/inputs/audio/a.wav")
    monkeypatch.setattr(heygem_mod.time, "sleep", lambda _: None)

    def fake_poll_task(**kwargs):
        return {
            "code": 10000,
            "data": {
                "status": 1,
                "progress": 100,
                "result": "/code/data/temp/task-1/result.avi",
            },
        }

    monkeypatch.setattr(provider, "_poll_task", fake_poll_task)

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def post(self, url: str, headers: dict[str, str], json: dict[str, object]):
            return FakeResponse({"code": 10000, "msg": "", "data": {}, "success": True})

    result = provider._execute_segment(
        client=FakeClient(),
        headers={},
        request={
            "job_id": "job-1",
            "submit_endpoint": "http://127.0.0.1:49202/easy/submit",
        },
        presenter_source="/code/data/inputs/video/presenter.mp4",
        segment={
            "segment_id": "avatar_seg_001",
            "audio_url": "C:/tmp/a.wav",
        },
    )

    assert result["status"] == "success"
    assert result["local_result_path"] == str(result_path)


def test_heygem_execute_segment_marks_completed_payload_without_local_result_as_failed(monkeypatch, tmp_path: Path):
    import roughcut.providers.avatar.heygem as heygem_mod

    provider = HeyGemAvatarProvider()
    shared_root = tmp_path / "heygem"
    shared_root.mkdir(parents=True, exist_ok=True)
    _stub_missing_docker_env_file(monkeypatch, heygem_mod)
    monkeypatch.setattr(heygem_mod, "_DEFAULT_SHARED_ROOTS", (shared_root,))
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(shared_root))
    monkeypatch.setattr(heygem_mod, "_resolve_audio_source", lambda *args, **kwargs: "/code/data/inputs/audio/a.wav")
    monkeypatch.setattr(heygem_mod.time, "sleep", lambda _: None)

    def fake_poll_task(**kwargs):
        return {
            "code": 10000,
            "data": {
                "status": 1,
                "progress": 100,
                "result": "/code/data/temp/task-missing/result.avi",
            },
        }

    monkeypatch.setattr(provider, "_poll_task", fake_poll_task)

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def post(self, url: str, headers: dict[str, str], json: dict[str, object]):
            return FakeResponse({"code": 10000, "msg": "", "data": {}, "success": True})

    result = provider._execute_segment(
        client=FakeClient(),
        headers={},
        request={
            "job_id": "job-1",
            "submit_endpoint": "http://127.0.0.1:49202/easy/submit",
        },
        presenter_source="/code/data/inputs/video/presenter.mp4",
        segment={
            "segment_id": "avatar_seg_001",
            "audio_url": "C:/tmp/a.wav",
        },
    )

    assert result["status"] == "failed"
    assert result["local_result_path"] is None


def test_heygem_execute_segment_retries_busy_submit(monkeypatch):
    import roughcut.providers.avatar.heygem as heygem_mod

    provider = HeyGemAvatarProvider()
    monkeypatch.setattr(heygem_mod, "_resolve_audio_source", lambda *args, **kwargs: "/code/data/inputs/audio/a.wav")
    monkeypatch.setattr(heygem_mod, "_resolve_local_result_path", lambda value: value)
    monkeypatch.setattr(heygem_mod, "_wait_for_result_file_ready", lambda value: value)
    monkeypatch.setattr(heygem_mod.time, "sleep", lambda _: None)

    poll_calls = {"count": 0}

    def fake_poll_task(**kwargs):
        poll_calls["count"] += 1
        return {
            "code": 10000,
            "data": {
                "status": 2,
                "progress": 100,
                "result": "C:/result.mp4",
            },
        }

    monkeypatch.setattr(provider, "_poll_task", fake_poll_task)

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def post(self, url: str, headers: dict[str, str], json: dict[str, object]):
            self.calls += 1
            if self.calls < 3:
                return FakeResponse({"code": 10001, "msg": "忙碌", "data": {}, "success": True})
            return FakeResponse({"code": 10000, "msg": "", "data": {}, "success": True})

    client = FakeClient()
    result = provider._execute_segment(
        client=client,
        headers={},
        request={
            "job_id": "job-1",
            "submit_endpoint": "http://127.0.0.1:49202/easy/submit",
        },
        presenter_source="/code/data/inputs/video/presenter.mp4",
        segment={
            "segment_id": "avatar_seg_001",
            "audio_url": "C:/tmp/a.wav",
        },
    )

    assert client.calls == 3
    assert poll_calls["count"] == 1
    assert result["status"] == "success"
    assert result["local_result_path"] == "C:/result.mp4"


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
