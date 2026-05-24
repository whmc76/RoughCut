from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

import roughcut.media.render as render_module
from roughcut.media.render import _ffmpeg_base_cmd, _run_process, _video_encode_args


@pytest.mark.asyncio
async def test_run_process_captures_stdout_and_stderr() -> None:
    result = await _run_process(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        timeout=10,
    )

    assert result.returncode == 0
    assert "out" in result.stdout
    assert "err" in result.stderr


@pytest.mark.asyncio
async def test_run_process_times_out() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        await _run_process(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=1,
        )


def test_render_thread_settings_are_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        render_module,
        "get_settings",
        lambda: SimpleNamespace(
            render_ffmpeg_threads=8,
            render_ffmpeg_filter_threads=4,
            render_video_encoder="libx264",
            render_cpu_preset="veryfast",
            render_crf=19,
        ),
    )

    assert _ffmpeg_base_cmd() == ["ffmpeg", "-y", "-filter_threads", "4"]

    encode_args = _video_encode_args(prefer_hardware=False)
    assert encode_args[encode_args.index("-threads") + 1] == "8"
