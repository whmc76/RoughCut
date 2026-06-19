from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from typing import Any


async def close_asyncio_subprocess_transport(process: asyncio.subprocess.Process | Any) -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, stream_name, None)
        if stream is None:
            continue
        close = getattr(stream, "close", None)
        if callable(close):
            with suppress(Exception):
                close()
        wait_closed = getattr(stream, "wait_closed", None)
        if callable(wait_closed):
            with suppress(Exception):
                await wait_closed()

    transport = getattr(process, "_transport", None)
    pipes = getattr(transport, "_pipes", None)
    if isinstance(pipes, dict):
        for pipe_protocol in list(pipes.values()):
            pipe_transport = getattr(pipe_protocol, "pipe", None)
            if pipe_transport is not None:
                with suppress(Exception):
                    pipe_transport.close()
    if transport is not None:
        with suppress(Exception):
            transport.close()

    if os.name == "nt":
        for _ in range(3):
            await asyncio.sleep(0)
