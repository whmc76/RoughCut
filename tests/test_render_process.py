from __future__ import annotations

import subprocess
import sys

import pytest

from roughcut.media.render import _run_process


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
