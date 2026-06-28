from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.pipeline import steps as pipeline_steps
from roughcut.pipeline.steps import (
    _AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS,
    _AVATAR_FULL_TRACK_CALL_TIMEOUT_SECONDS,
    _AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS,
    AvatarFullTrackRenderError,
    _avatar_full_track_error_payload,
    _avatar_full_track_file_fingerprint,
    _avatar_full_track_segment_cache_key,
    _avatar_full_track_segment_cache_path,
    _merge_render_runtime_result,
    _overlay_avatar_picture_in_picture,
    _render_full_track_avatar_video,
    _resolve_avatar_full_track_busy_max_wait_seconds,
    _resolve_avatar_full_track_call_timeout_seconds,
    _resolve_avatar_full_track_execution_timeout_seconds,
    _resolve_avatar_full_track_slot_timeout_seconds,
    _execute_avatar_full_track_render_request,
    _hold_avatar_full_track_slot,
)


def test_resolve_avatar_full_track_busy_wait_uses_default_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROUGHCUT_AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS", raising=False)

    assert (
        _resolve_avatar_full_track_busy_max_wait_seconds()
        == _AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS
    )


def test_resolve_avatar_full_track_busy_wait_parses_and_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUGHCUT_AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS", "12")

    assert _resolve_avatar_full_track_busy_max_wait_seconds() == 30.0


def test_resolve_avatar_full_track_busy_wait_invalid_value_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUGHCUT_AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS", "abc")

    assert (
        _resolve_avatar_full_track_busy_max_wait_seconds()
        == _AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS
    )


def test_resolve_avatar_full_track_call_timeout_has_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUGHCUT_AVATAR_FULL_TRACK_CALL_TIMEOUT_SECONDS", "5")

    assert _resolve_avatar_full_track_call_timeout_seconds() == 10.0


def test_resolve_avatar_full_track_execution_timeout_uses_provider_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROUGHCUT_AVATAR_FULL_TRACK_CALL_TIMEOUT_SECONDS", raising=False)

    provider = SimpleNamespace(estimate_render_timeout_seconds=lambda *, request: 640.0)

    assert (
        _resolve_avatar_full_track_execution_timeout_seconds(
            provider=provider,
            render_request={"request_id": "test"},
        )
        == 640.0
    )


def test_resolve_avatar_full_track_slot_timeout_uses_default_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROUGHCUT_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS", raising=False)

    assert (
        _resolve_avatar_full_track_slot_timeout_seconds()
        == _AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS
    )


@pytest.mark.asyncio
async def test_overlay_avatar_picture_in_picture_limits_full_track_to_main_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    base_path = tmp_path / "packaged.mp4"
    avatar_path = tmp_path / "avatar.mp4"
    output_path = tmp_path / "avatar_pip.mp4"
    base_path.write_bytes(b"base")
    avatar_path.write_bytes(b"avatar")
    observed: dict[str, str] = {}

    async def fake_probe(path: Path) -> SimpleNamespace:
        if path == base_path:
            return SimpleNamespace(duration=110.0, width=1920, height=1080, fps=30.0)
        if path == avatar_path:
            return SimpleNamespace(duration=100.0, width=512, height=512, fps=30.0)
        return SimpleNamespace(duration=0.0, width=0, height=0, fps=0.0)

    def fake_run(cmd, **_kwargs):
        observed["filter_complex"] = cmd[cmd.index("-filter_complex") + 1]
        output_path.write_bytes(b"output")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(pipeline_steps, "probe", fake_probe)
    monkeypatch.setattr(pipeline_steps.subprocess, "run", fake_run)
    monkeypatch.setattr(
        pipeline_steps,
        "get_settings",
        lambda: SimpleNamespace(ffmpeg_timeout_sec=30),
    )

    await _overlay_avatar_picture_in_picture(
        base_video_path=base_path,
        avatar_video_path=avatar_path,
        output_path=output_path,
        position="bottom_right",
        scale=0.22,
        margin=28,
        overlay_start_time=6.0,
        overlay_duration_sec=100.0,
    )

    filter_complex = observed["filter_complex"]
    assert "enable='between(t,6.000000,106.000000)'" in filter_complex
    assert "setpts=PTS-STARTPTS+6.000000/TB" in filter_complex
    assert "trim=duration=100.000000" in filter_complex


def test_resolve_avatar_full_track_slot_timeout_parses_and_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUGHCUT_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS", "1")

    assert _resolve_avatar_full_track_slot_timeout_seconds() == 3.0


def test_resolve_avatar_full_track_slot_timeout_invalid_value_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUGHCUT_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS", "abc")

    assert (
        _resolve_avatar_full_track_slot_timeout_seconds()
        == _AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS
    )


@pytest.mark.asyncio
async def test_execute_avatar_full_track_render_request_respects_busy_wait_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_execute_render(*, job_id: str, request: dict) -> dict:
        nonlocal calls
        del job_id
        del request
        calls += 1
        raise RuntimeError("service busy, retry later")

    @asynccontextmanager
    async def fake_hold_avatar_full_track_slot(*, job_id: str):
        del job_id
        yield

    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("roughcut.pipeline.steps._hold_avatar_full_track_slot", fake_hold_avatar_full_track_slot)
    monkeypatch.setattr("roughcut.pipeline.steps.get_avatar_provider", lambda: SimpleNamespace(execute_render=fake_execute_render))
    monkeypatch.setattr("roughcut.pipeline.steps.asyncio.sleep", fake_sleep)
    monkeypatch.setenv("ROUGHCUT_AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS", "25")

    with pytest.raises(AvatarFullTrackRenderError, match="service busy, retry later") as exc_info:
        await _execute_avatar_full_track_render_request(
            job_id="job-id",
            render_request={"request_id": "test"},
        )

    assert calls == 3
    assert exc_info.value.reason_code == "avatar_full_track_busy_exhausted"
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_execute_avatar_full_track_render_request_respects_call_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_execute_render(*, job_id: str, request: dict) -> dict:
        del job_id
        del request
        nonlocal calls
        calls += 1
        time.sleep(1.0)
        return {
            "provider": "mock",
            "segments": [],
        }

    @asynccontextmanager
    async def fake_hold_avatar_full_track_slot(*, job_id: str):
        del job_id
        yield

    monkeypatch.setattr("roughcut.pipeline.steps._hold_avatar_full_track_slot", fake_hold_avatar_full_track_slot)
    monkeypatch.setattr(
        "roughcut.pipeline.steps.get_avatar_provider",
        lambda: SimpleNamespace(
            execute_render=fake_execute_render,
            estimate_render_timeout_seconds=lambda *, request: 0.05,
        ),
    )
    monkeypatch.setattr(
        "roughcut.pipeline.steps._resolve_avatar_full_track_execution_timeout_seconds",
        lambda *, provider, render_request: 0.05,
    )

    with pytest.raises(AvatarFullTrackRenderError, match="avatar_full_track_call_timeout") as exc_info:
        await _execute_avatar_full_track_render_request(
            job_id="job-id",
            render_request={"request_id": "test"},
        )

    assert calls == 1
    assert exc_info.value.reason_code == "avatar_full_track_call_timeout"
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_hold_avatar_full_track_slot_raises_typed_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        del func, args, kwargs
        return (False, None)

    monkeypatch.setattr("roughcut.pipeline.steps.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("roughcut.pipeline.steps._resolve_avatar_full_track_slot_timeout_seconds", lambda: 12.0)

    with pytest.raises(AvatarFullTrackRenderError, match="avatar_full_track_slot_timeout") as exc_info:
        async with _hold_avatar_full_track_slot(job_id="job-id"):
            raise AssertionError("should not enter slot context")

    assert exc_info.value.reason_code == "avatar_full_track_slot_timeout"
    assert exc_info.value.retryable is True
    assert exc_info.value.metadata == {"slot_timeout_seconds": 12.0}


def test_avatar_full_track_error_payload_preserves_reason_and_metadata() -> None:
    exc = AvatarFullTrackRenderError(
        "avatar_full_track_call_timeout>45.0s",
        reason_code="avatar_full_track_call_timeout",
        retryable=True,
        metadata={"call_timeout_seconds": 45.0},
    )

    assert _avatar_full_track_error_payload(exc) == {
        "reason": "avatar_full_track_call_timeout",
        "detail": "avatar_full_track_call_timeout>45.0s",
        "retryable": True,
        "error_metadata": {"call_timeout_seconds": 45.0},
    }


def test_merge_render_runtime_result_clears_stale_error_fields_after_success() -> None:
    merged = _merge_render_runtime_result(
        {
            "status": "degraded",
            "reason": "avatar_full_track_call_timeout",
            "retryable": True,
            "error_metadata": {"call_timeout_seconds": 180.0},
            "output_path": "C:/temp/avatar.mp4",
        },
        {
            "status": "done",
            "detail": "数字人口播已作为画中画写入成片。",
            "output_path": "E:/output/avatar.mp4",
        },
    )

    assert merged == {
        "status": "done",
        "detail": "数字人口播已作为画中画写入成片。",
        "output_path": "E:/output/avatar.mp4",
    }


@pytest.mark.asyncio
async def test_render_full_track_avatar_video_raises_typed_error_when_presenter_missing(tmp_path) -> None:
    source_plain_video_path = tmp_path / "plain.mp4"
    source_plain_video_path.write_bytes(b"")

    with pytest.raises(AvatarFullTrackRenderError, match="avatar_full_track_presenter_missing") as exc_info:
        await _render_full_track_avatar_video(
            job_id="job-id",
            avatar_plan={},
            source_plain_video_path=source_plain_video_path,
            debug_dir=None,
        )

    assert exc_info.value.reason_code == "avatar_full_track_presenter_missing"


@pytest.mark.asyncio
async def test_render_full_track_avatar_video_uses_unique_drive_audio_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source_plain_video_path = tmp_path / "output_plain.mp4"
    source_plain_video_path.write_bytes(b"video")
    result_path = tmp_path / "avatar.mp4"
    result_path.write_bytes(b"avatar")
    submitted_audio_urls: list[str] = []

    async def fake_extract_audio(_source_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"wav")

    async def fake_execute_avatar_full_track_render_request(*, job_id: str, render_request: dict) -> dict:
        del job_id
        submitted_audio_urls.append(render_request["segments"][0]["audio_url"])
        return {
            "segments": [
                {
                    "status": "success",
                    "local_result_path": str(result_path),
                }
            ]
        }

    async def fake_probe(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(duration=12.0)

    monkeypatch.setattr(pipeline_steps, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(pipeline_steps, "probe", fake_probe)
    monkeypatch.setattr(
        pipeline_steps,
        "_execute_avatar_full_track_render_request",
        fake_execute_avatar_full_track_render_request,
    )
    monkeypatch.setattr(
        pipeline_steps,
        "get_settings",
        lambda: SimpleNamespace(
            avatar_provider="heygem",
            avatar_api_base_url="http://heygem",
            avatar_layout_template="picture_in_picture",
        ),
    )

    for _ in range(2):
        assert await _render_full_track_avatar_video(
            job_id="job-id",
            avatar_plan={"presenter_id": "presenter"},
            source_plain_video_path=source_plain_video_path,
            debug_dir=None,
        ) == result_path

    assert len(submitted_audio_urls) == 2
    assert submitted_audio_urls[0] != submitted_audio_urls[1]
    assert submitted_audio_urls[0].startswith(str(tmp_path))
    assert ".avatar_drive." in submitted_audio_urls[0]


@pytest.mark.asyncio
async def test_render_full_track_avatar_video_loops_short_local_presenter_before_submit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source_plain_video_path = tmp_path / "output_plain.mp4"
    source_plain_video_path.write_bytes(b"video")
    presenter_path = tmp_path / "presenter.mp4"
    presenter_path.write_bytes(b"presenter")
    result_path = tmp_path / "avatar.mp4"
    result_path.write_bytes(b"avatar")
    submitted_presenter_ids: list[str] = []
    loop_calls: list[tuple[Path, Path, float]] = []

    async def fake_extract_audio(_source_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"wav")

    def fake_loop_presenter_video(*, source_path: Path, target_path: Path, target_duration_sec: float) -> None:
        loop_calls.append((source_path, target_path, target_duration_sec))
        target_path.write_bytes(b"looped presenter")

    async def fake_execute_avatar_full_track_render_request(*, job_id: str, render_request: dict) -> dict:
        del job_id
        submitted_presenter_ids.append(render_request["presenter_id"])
        return {
            "segments": [
                {
                    "status": "success",
                    "local_result_path": str(result_path),
                }
            ]
        }

    async def fake_probe(path: Path) -> SimpleNamespace:
        if path == source_plain_video_path:
            return SimpleNamespace(duration=30.0)
        if path == presenter_path:
            return SimpleNamespace(duration=5.0)
        if path == result_path or ".avatar_full_track_loop." in path.name:
            return SimpleNamespace(duration=30.0)
        return SimpleNamespace(duration=0.0)

    monkeypatch.setattr(pipeline_steps, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(pipeline_steps, "probe", fake_probe)
    monkeypatch.setattr(pipeline_steps, "_render_looped_avatar_presenter_video", fake_loop_presenter_video)
    monkeypatch.setattr(
        pipeline_steps,
        "_execute_avatar_full_track_render_request",
        fake_execute_avatar_full_track_render_request,
    )
    monkeypatch.setattr(
        pipeline_steps,
        "get_settings",
        lambda: SimpleNamespace(
            avatar_provider="heygem",
            avatar_api_base_url="http://heygem",
            avatar_layout_template="picture_in_picture",
        ),
    )

    assert await _render_full_track_avatar_video(
        job_id="job-id",
        avatar_plan={"presenter_id": str(presenter_path)},
        source_plain_video_path=source_plain_video_path,
        debug_dir=None,
    ) == result_path

    assert loop_calls == [(presenter_path, Path(submitted_presenter_ids[0]), 30.0)]
    assert submitted_presenter_ids[0] != str(presenter_path)
    assert ".avatar_full_track_loop." in submitted_presenter_ids[0]


@pytest.mark.asyncio
async def test_render_full_track_avatar_video_rejects_short_provider_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source_plain_video_path = tmp_path / "output_plain.mp4"
    source_plain_video_path.write_bytes(b"video")
    result_path = tmp_path / "avatar.mp4"
    result_path.write_bytes(b"avatar")

    async def fake_extract_audio(_source_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"wav")

    async def fake_execute_avatar_full_track_render_request(*, job_id: str, render_request: dict) -> dict:
        del job_id, render_request
        return {
            "segments": [
                {
                    "status": "success",
                    "local_result_path": str(result_path),
                }
            ]
        }

    async def fake_probe(path: Path) -> SimpleNamespace:
        if path == source_plain_video_path:
            return SimpleNamespace(duration=30.0)
        if path == result_path:
            return SimpleNamespace(duration=5.0)
        return SimpleNamespace(duration=30.0)

    monkeypatch.setattr(pipeline_steps, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(pipeline_steps, "probe", fake_probe)
    monkeypatch.setattr(
        pipeline_steps,
        "_execute_avatar_full_track_render_request",
        fake_execute_avatar_full_track_render_request,
    )
    monkeypatch.setattr(
        pipeline_steps,
        "get_settings",
        lambda: SimpleNamespace(
            avatar_provider="heygem",
            avatar_api_base_url="http://heygem",
            avatar_layout_template="picture_in_picture",
        ),
    )

    with pytest.raises(AvatarFullTrackRenderError, match="avatar_full_track_result_too_short") as exc_info:
        await _render_full_track_avatar_video(
            job_id="job-id",
            avatar_plan={"presenter_id": "presenter"},
            source_plain_video_path=source_plain_video_path,
            debug_dir=None,
        )

    assert exc_info.value.reason_code == "avatar_full_track_result_too_short"
    assert exc_info.value.metadata == {
        "result_path": str(result_path),
        "result_duration_sec": 5.0,
        "expected_duration_sec": 30.0,
        "segment_id": "avatar_full_track",
    }


@pytest.mark.asyncio
async def test_render_full_track_avatar_video_splits_long_tracks_before_submit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source_plain_video_path = tmp_path / "output_plain.mp4"
    source_plain_video_path.write_bytes(b"video")
    result_paths = [tmp_path / f"avatar_part_{index}.mp4" for index in range(3)]
    submitted_segments: list[dict] = []
    concat_calls: list[list[Path]] = []

    async def fake_extract_audio(_source_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"wav")

    async def fake_extract_audio_clip(_input_path: Path, output_path: Path, *, start_time: float, end_time: float) -> None:
        output_path.write_bytes(f"{start_time}-{end_time}".encode("utf-8"))

    async def fake_execute_avatar_full_track_render_request(*, job_id: str, render_request: dict) -> dict:
        del job_id
        submitted_segments.extend(render_request["segments"])
        segments = []
        for index, result_path in enumerate(result_paths):
            result_path.write_bytes(b"avatar")
            segments.append(
                {
                    "segment_id": render_request["segments"][index]["segment_id"],
                    "status": "success",
                    "local_result_path": str(result_path),
                }
            )
        return {"segments": segments}

    async def fake_concat_avatar_video_segments(*, result_paths: list[Path], output_path: Path) -> Path:
        concat_calls.append(list(result_paths))
        output_path.write_bytes(b"concat")
        return output_path

    async def fake_probe(path: Path) -> SimpleNamespace:
        if path in result_paths[:2] or "part_00" in path.name or "part_01" in path.name:
            return SimpleNamespace(duration=180.0)
        if path == result_paths[2] or "part_02" in path.name:
            return SimpleNamespace(duration=75.0)
        if path == source_plain_video_path or ".avatar_full_track." in path.name:
            return SimpleNamespace(duration=435.0)
        return SimpleNamespace(duration=0.0)

    monkeypatch.setattr(pipeline_steps, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(pipeline_steps, "extract_audio_clip", fake_extract_audio_clip)
    monkeypatch.setattr(pipeline_steps, "probe", fake_probe)
    monkeypatch.setattr(pipeline_steps, "_concat_avatar_video_segments", fake_concat_avatar_video_segments)
    monkeypatch.setattr(
        pipeline_steps,
        "_execute_avatar_full_track_render_request",
        fake_execute_avatar_full_track_render_request,
    )
    monkeypatch.setattr(
        pipeline_steps,
        "get_settings",
        lambda: SimpleNamespace(
            avatar_provider="heygem",
            avatar_api_base_url="http://heygem",
            avatar_layout_template="picture_in_picture",
            ffmpeg_timeout_sec=120,
        ),
    )

    result = await _render_full_track_avatar_video(
        job_id="job-id",
        avatar_plan={"presenter_id": "presenter"},
        source_plain_video_path=source_plain_video_path,
        debug_dir=None,
    )

    assert result.name.startswith("output_plain.avatar_full_track.")
    assert [segment["duration_sec"] for segment in submitted_segments] == [180.0, 180.0, 75.0]
    assert [segment["start_time"] for segment in submitted_segments] == [0.0, 180.0, 360.0]
    assert [path.name.startswith(f"avatar_full_track.avatar_full_track_part_0{index}.") for index, path in enumerate(concat_calls[0])] == [
        True,
        True,
        True,
    ]
    assert all(path.name.endswith(".cache.mp4") for path in concat_calls[0])


@pytest.mark.asyncio
async def test_render_full_track_avatar_video_reuses_verified_segment_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source_plain_video_path = tmp_path / "output_plain.mp4"
    source_plain_video_path.write_bytes(b"video")
    fingerprint_audio_path = tmp_path / "fingerprint.wav"
    fingerprint_audio_path.write_bytes(b"wav")
    source_audio_fingerprint = _avatar_full_track_file_fingerprint(fingerprint_audio_path)
    first_segment_cache_key = _avatar_full_track_segment_cache_key(
        segment={"segment_id": "avatar_full_track_part_00", "start_time": 0.0, "duration_sec": 180.0},
        source_audio_fingerprint=source_audio_fingerprint,
    )
    cached_first = _avatar_full_track_segment_cache_path(
        cache_dir=tmp_path,
        segment_id="avatar_full_track_part_00",
        cache_key=first_segment_cache_key,
        suffix=".mp4",
    )
    cached_first.write_bytes(b"cached")
    provider_results = [tmp_path / "avatar_part_01.mp4", tmp_path / "avatar_part_02.mp4"]
    submitted_segment_ids: list[str] = []
    concat_calls: list[list[Path]] = []

    async def fake_extract_audio(_source_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"wav")

    async def fake_extract_audio_clip(_input_path: Path, output_path: Path, *, start_time: float, end_time: float) -> None:
        output_path.write_bytes(f"{start_time}-{end_time}".encode("utf-8"))

    async def fake_execute_avatar_full_track_render_request(*, job_id: str, render_request: dict) -> dict:
        del job_id
        submitted_segment_ids.extend(segment["segment_id"] for segment in render_request["segments"])
        segments = []
        for requested_segment, result_path in zip(render_request["segments"], provider_results, strict=True):
            result_path.write_bytes(b"avatar")
            segments.append(
                {
                    "segment_id": requested_segment["segment_id"],
                    "status": "success",
                    "local_result_path": str(result_path),
                }
            )
        return {"segments": segments}

    async def fake_concat_avatar_video_segments(*, result_paths: list[Path], output_path: Path) -> Path:
        concat_calls.append(list(result_paths))
        output_path.write_bytes(b"concat")
        return output_path

    async def fake_probe(path: Path) -> SimpleNamespace:
        name = path.name
        if path == source_plain_video_path or (".avatar_full_track." in name and ".cache" not in name):
            return SimpleNamespace(duration=435.0)
        if "part_02" in name:
            return SimpleNamespace(duration=75.0)
        if "part_00" in name or "part_01" in name:
            return SimpleNamespace(duration=180.0)
        return SimpleNamespace(duration=0.0)

    monkeypatch.setattr(pipeline_steps, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(pipeline_steps, "extract_audio_clip", fake_extract_audio_clip)
    monkeypatch.setattr(pipeline_steps, "probe", fake_probe)
    monkeypatch.setattr(pipeline_steps, "_concat_avatar_video_segments", fake_concat_avatar_video_segments)
    monkeypatch.setattr(
        pipeline_steps,
        "_execute_avatar_full_track_render_request",
        fake_execute_avatar_full_track_render_request,
    )
    monkeypatch.setattr(
        pipeline_steps,
        "get_settings",
        lambda: SimpleNamespace(
            avatar_provider="heygem",
            avatar_api_base_url="http://heygem",
            avatar_layout_template="picture_in_picture",
            ffmpeg_timeout_sec=120,
        ),
    )

    result = await _render_full_track_avatar_video(
        job_id="job-id",
        avatar_plan={"presenter_id": "presenter"},
        source_plain_video_path=source_plain_video_path,
        debug_dir=None,
    )

    assert result.name.startswith("output_plain.avatar_full_track.")
    assert submitted_segment_ids == ["avatar_full_track_part_01", "avatar_full_track_part_02"]
    assert concat_calls
    assert concat_calls[0][0] == cached_first
    assert "avatar_full_track_part_01" in concat_calls[0][1].name
    assert "avatar_full_track_part_02" in concat_calls[0][2].name
    assert concat_calls[0][1].name.endswith(".cache.mp4")
    assert concat_calls[0][2].name.endswith(".cache.mp4")


@pytest.mark.asyncio
async def test_render_full_track_avatar_video_caches_successful_segments_before_busy_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source_plain_video_path = tmp_path / "output_plain.mp4"
    source_plain_video_path.write_bytes(b"video")
    fingerprint_audio_path = tmp_path / "fingerprint.wav"
    fingerprint_audio_path.write_bytes(b"wav")
    source_audio_fingerprint = _avatar_full_track_file_fingerprint(fingerprint_audio_path)
    result_path = tmp_path / "avatar_part_00.mp4"
    result_path.write_bytes(b"avatar")

    async def fake_extract_audio(_source_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"wav")

    async def fake_extract_audio_clip(_input_path: Path, output_path: Path, *, start_time: float, end_time: float) -> None:
        output_path.write_bytes(f"{start_time}-{end_time}".encode("utf-8"))

    async def fake_execute_avatar_full_track_render_request(*, job_id: str, render_request: dict) -> dict:
        del job_id
        return {
            "segments": [
                {
                    "segment_id": render_request["segments"][0]["segment_id"],
                    "status": "success",
                    "local_result_path": str(result_path),
                },
                {
                    "segment_id": render_request["segments"][1]["segment_id"],
                    "status": "failed",
                    "error": "忙碌中",
                },
            ]
        }

    async def fake_probe(path: Path) -> SimpleNamespace:
        name = path.name
        if path == source_plain_video_path:
            return SimpleNamespace(duration=435.0)
        if "part_00" in name:
            return SimpleNamespace(duration=180.0)
        return SimpleNamespace(duration=0.0)

    monkeypatch.setattr(pipeline_steps, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(pipeline_steps, "extract_audio_clip", fake_extract_audio_clip)
    monkeypatch.setattr(pipeline_steps, "probe", fake_probe)
    monkeypatch.setattr(
        pipeline_steps,
        "_execute_avatar_full_track_render_request",
        fake_execute_avatar_full_track_render_request,
    )
    monkeypatch.setattr(
        pipeline_steps,
        "get_settings",
        lambda: SimpleNamespace(
            avatar_provider="heygem",
            avatar_api_base_url="http://heygem",
            avatar_layout_template="picture_in_picture",
        ),
    )

    with pytest.raises(AvatarFullTrackRenderError, match="忙碌中") as exc_info:
        await _render_full_track_avatar_video(
            job_id="job-id",
            avatar_plan={"presenter_id": "presenter"},
            source_plain_video_path=source_plain_video_path,
            debug_dir=None,
        )

    cached_first = _avatar_full_track_segment_cache_path(
        cache_dir=tmp_path,
        segment_id="avatar_full_track_part_00",
            cache_key=_avatar_full_track_segment_cache_key(
                segment={"segment_id": "avatar_full_track_part_00", "start_time": 0.0, "duration_sec": 180.0},
                source_audio_fingerprint=source_audio_fingerprint,
            ),
        suffix=".mp4",
    )
    assert cached_first.exists()
    assert exc_info.value.metadata["cached_segment_ids"] == ["avatar_full_track_part_00"]
