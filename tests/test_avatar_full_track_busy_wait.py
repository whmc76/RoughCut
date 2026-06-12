from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from roughcut.pipeline.steps import (
    _AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS,
    _AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS,
    AvatarFullTrackRenderError,
    _avatar_full_track_error_payload,
    _resolve_avatar_full_track_busy_max_wait_seconds,
    _resolve_avatar_full_track_call_timeout_seconds,
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


def test_resolve_avatar_full_track_slot_timeout_uses_default_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROUGHCUT_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS", raising=False)

    assert (
        _resolve_avatar_full_track_slot_timeout_seconds()
        == _AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS
    )


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
    monkeypatch.setattr("roughcut.pipeline.steps.get_avatar_provider", lambda: SimpleNamespace(execute_render=fake_execute_render))
    monkeypatch.setattr(
        "roughcut.pipeline.steps._resolve_avatar_full_track_call_timeout_seconds",
        lambda: 0.05,
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
