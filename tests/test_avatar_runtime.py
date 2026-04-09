from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.avatar.runtime import (
    _ensure_voice_prepared,
    _is_heygem_training_only_service,
    _prepare_direct_preview_audio,
    _submit_heygem_preview_to_base,
    heygem_shared_root,
)


@pytest.mark.asyncio
async def test_ensure_voice_prepared_retries_when_only_preprocess_error_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.avatar.runtime as runtime_mod

    normalized = tmp_path / "voice.wav"
    normalized.write_bytes(b"wav")

    file_record = {
        "artifacts": {
            "normalized_wav_path": str(normalized),
            "training_reference_name": "voice.wav",
            "training_preprocess_error": "CUDA error: unknown error",
        }
    }

    async def fake_training_available() -> bool:
        return True

    async def fake_prepare_voice_sample_artifacts(
        incoming: dict[str, object],
        *,
        attempt_preprocess: bool = True,
        require_preprocess: bool = False,
    ):
        assert incoming is file_record
        assert attempt_preprocess is True
        assert require_preprocess is False
        incoming["artifacts"] = {
            "normalized_wav_path": str(normalized),
            "training_reference_name": "voice.wav",
            "training_preprocess": {
                "reference_audio_text": "测试参考文本",
                "asr_format_audio_url": "/code/data/voice.wav",
            },
        }
        return incoming

    monkeypatch.setattr(runtime_mod, "is_heygem_training_available", fake_training_available)
    monkeypatch.setattr(runtime_mod, "prepare_voice_sample_artifacts", fake_prepare_voice_sample_artifacts)

    prepared = await _ensure_voice_prepared(file_record)

    assert prepared["artifacts"]["training_preprocess"]["reference_audio_text"] == "测试参考文本"


@pytest.mark.asyncio
async def test_ensure_voice_prepared_keeps_existing_training_preprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.avatar.runtime as runtime_mod

    normalized = tmp_path / "voice.wav"
    normalized.write_bytes(b"wav")

    file_record = {
        "artifacts": {
            "normalized_wav_path": str(normalized),
            "training_reference_name": "voice.wav",
            "training_preprocess": {
                "reference_audio_text": "已存在文本",
                "asr_format_audio_url": "/code/data/voice.wav",
            },
        }
    }

    async def fail_prepare(*_args, **_kwargs):
        raise AssertionError("prepare_voice_sample_artifacts should not be called")

    monkeypatch.setattr(runtime_mod, "prepare_voice_sample_artifacts", fail_prepare)

    prepared = await _ensure_voice_prepared(file_record)

    assert prepared is file_record


@pytest.mark.asyncio
async def test_prepare_direct_preview_audio_trims_to_video_and_preview_limit(
    tmp_path: Path,
):
    source_audio = tmp_path / "source.wav"
    source_video = tmp_path / "source.mp4"
    output_audio = tmp_path / "trimmed.wav"

    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=125",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(source_audio),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=736x992:d=93",
            "-r",
            "25",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source_video),
        ],
        check=True,
        capture_output=True,
    )

    prepared_path = await _prepare_direct_preview_audio(
        source_audio_path=source_audio,
        output_path=output_audio,
        script="大家好，我是赛博迪克朗。",
        source_video_path=source_video,
    )

    assert prepared_path == output_audio
    assert output_audio.exists()

    import roughcut.avatar.runtime as runtime_mod

    meta = await runtime_mod.probe(output_audio)
    assert meta.duration is not None
    assert float(meta.duration) <= 18.2
    assert float(meta.duration) >= 1.5


@pytest.mark.asyncio
async def test_submit_heygem_preview_surfaces_query_failure_without_masking_endpoint(
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx
    import roughcut.avatar.runtime as runtime_mod

    async def fake_training_only_service(_base_url: str):
        return False

    class FakeResponse:
        def __init__(self, payload: dict[str, object]):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict[str, object]):
            assert url.endswith("/easy/submit")
            return FakeResponse({"code": 10000, "msg": "ok"})

        async def get(self, url: str, params: dict[str, object]):
            assert url.endswith("/easy/query")
            return FakeResponse({"data": {"status": 3, "msg": "三次获取音频时长失败"}})

    monkeypatch.setattr(runtime_mod, "_is_heygem_training_only_service", fake_training_only_service)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="三次获取音频时长失败"):
        await _submit_heygem_preview_to_base(
            audio_name="preview.wav",
            video_url="/code/data/inputs/video/presenter.mp4",
            task_code="preview-task",
            base_url="http://127.0.0.1:49202",
        )


@pytest.mark.asyncio
async def test_submit_heygem_preview_treats_missing_task_as_success_when_result_file_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx
    import roughcut.avatar.runtime as runtime_mod

    shared_root = tmp_path / "heygem"
    (shared_root / "temp").mkdir(parents=True, exist_ok=True)
    (shared_root / "temp" / "preview-task-r.mp4").write_bytes(b"video")
    monkeypatch.setattr(runtime_mod, "_DEFAULT_HEYGEM_ROOT", shared_root)

    async def fake_training_only_service(_base_url: str):
        return False

    class FakeResponse:
        def __init__(self, payload: dict[str, object]):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict[str, object]):
            assert url.endswith("/easy/submit")
            return FakeResponse({"code": 10000, "msg": "ok"})

        async def get(self, url: str, params: dict[str, object]):
            assert url.endswith("/easy/query")
            return FakeResponse({"code": 10004, "msg": "任务不存在", "data": {}})

    monkeypatch.setattr(runtime_mod, "_is_heygem_training_only_service", fake_training_only_service)
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    payload = await _submit_heygem_preview_to_base(
        audio_name="preview.wav",
        video_url="/code/data/inputs/video/presenter.mp4",
        task_code="preview-task",
        base_url="http://127.0.0.1:49202",
    )

    assert payload["status"] == 2
    assert payload["result"] == "/preview-task-r.mp4"


@pytest.mark.asyncio
async def test_is_heygem_training_only_service_does_not_treat_404_preview_probe_as_preview_capable(
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx
    import roughcut.avatar.runtime as runtime_mod

    runtime_mod._HEYGEM_PREVIEW_SERVICE_CACHE.clear()

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict[str, object] | None = None):
            self.status_code = status_code
            self._payload = payload or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("error", request=None, response=None)

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str):
            if url.endswith("/json"):
                return FakeResponse(404)
            if url.endswith("/easy/query?code=healthcheck"):
                return FakeResponse(404)
            raise AssertionError(f"unexpected GET {url}")

        async def post(self, url: str):
            assert url.endswith("/v1/health")
            return FakeResponse(200)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    assert await _is_heygem_training_only_service("http://127.0.0.1:49204") is True


def test_heygem_shared_root_prefers_host_dir_when_container_root_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    host_shared_root = tmp_path / "host-heygem"
    monkeypatch.setenv("HEYGEM_SHARED_ROOT", "/code/data")
    monkeypatch.setenv("HEYGEM_SHARED_HOST_DIR", str(host_shared_root))

    resolved = heygem_shared_root()

    assert resolved == host_shared_root
    assert (host_shared_root / "inputs" / "audio").exists()
    assert (host_shared_root / "inputs" / "video").exists()
    assert (host_shared_root / "temp").exists()
    assert (host_shared_root / "result").exists()


@pytest.mark.asyncio
async def test_render_full_track_avatar_video_raises_segment_error_instead_of_probing_empty_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.pipeline.steps as steps_mod

    source_video = tmp_path / "plain.mp4"
    source_video.write_bytes(b"video")
    source_audio = tmp_path / "plain.avatar_drive.wav"
    source_audio.write_bytes(b"audio")

    async def fake_extract_audio(source_path: Path, output_path: Path):
        assert source_path == source_video
        output_path.write_bytes(source_audio.read_bytes())

    class ProbeResult:
        def __init__(self, duration: float):
            self.duration = duration

    async def fake_probe(path: Path):
        assert path == source_video
        return ProbeResult(12.5)

    class FakeProvider:
        def execute_render(self, *, job_id: str, request: dict[str, object]):
            return {
                "status": "failed",
                "segments": [
                    {
                        "segment_id": "avatar_full_track",
                        "status": "failed",
                        "error": "任务不存在",
                        "local_result_path": "",
                    }
                ],
            }

    monkeypatch.setattr(steps_mod, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(steps_mod, "probe", fake_probe)
    monkeypatch.setattr(steps_mod, "get_avatar_provider", lambda: FakeProvider())

    with pytest.raises(RuntimeError, match="任务不存在"):
        await steps_mod._render_full_track_avatar_video(
            job_id="job-1",
            avatar_plan={"presenter_id": "presenter.mp4"},
            source_plain_video_path=source_video,
            debug_dir=tmp_path / "debug",
        )
