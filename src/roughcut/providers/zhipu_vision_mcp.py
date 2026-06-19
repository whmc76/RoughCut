from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.zhipu_compat import build_zhipu_mcp_server_catalog
from roughcut.utils.asyncio_subprocess import close_asyncio_subprocess_transport


class ZhipuVisionMCPError(RuntimeError):
    """Raised when the local Zhipu vision MCP server cannot be used."""


@dataclass(frozen=True, slots=True)
class VisionMCPAnalysisResult:
    image_path: str
    content: str
    raw: dict[str, Any]


class _StdioMCPClient:
    def __init__(
        self,
        *,
        command: str,
        args: list[str],
        env: dict[str, str],
        timeout_sec: int = 45,
    ) -> None:
        self._command = command
        self._args = list(args)
        self._env = dict(env)
        self._timeout_sec = max(5, int(timeout_sec))
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._stderr_chunks: list[str] = []
        self._stderr_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> _StdioMCPClient:
        self._process = await self._start()
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self._initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        process = self._process
        stderr_task = self._stderr_task
        self._process = None
        self._stderr_task = None
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if stderr_task is not None:
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass
        await close_asyncio_subprocess_transport(process)

    async def call_tool(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = await self._request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(payload, dict):
            raise ZhipuVisionMCPError("Vision MCP returned a non-object tool payload")
        return payload

    async def _start(self) -> asyncio.subprocess.Process:
        command: list[str]
        if os.name == "nt":
            command = ["cmd", "/c", self._command, *self._args]
        else:
            command = [self._command, *self._args]
        try:
            return await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as exc:
            raise ZhipuVisionMCPError(
                f"Vision MCP command not found: {' '.join(command)}"
            ) from exc

    async def _initialize(self) -> None:
        response = await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "roughcut", "version": "0.1"},
            },
        )
        if not isinstance(response, dict):
            raise ZhipuVisionMCPError("Vision MCP initialize returned a non-object payload")
        await self._notify("notifications/initialized", {})

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        self._request_id += 1
        request_id = self._request_id
        await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            message = await self._read_message()
            if not isinstance(message, dict):
                continue
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise ZhipuVisionMCPError(str((message.get("error") or {}).get("message") or "Vision MCP request failed"))
            return message.get("result")

    async def _send(self, payload: dict[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise ZhipuVisionMCPError("Vision MCP stdin is unavailable")
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        process.stdin.write(body)
        await process.stdin.drain()

    async def _read_message(self) -> dict[str, Any]:
        process = self._require_process()
        if process.stdout is None:
            raise ZhipuVisionMCPError("Vision MCP stdout is unavailable")
        line = await asyncio.wait_for(process.stdout.readline(), timeout=self._timeout_sec)
        if line == b"":
            stderr_text = await self._read_stderr_tail()
            raise ZhipuVisionMCPError(
                "Vision MCP server exited before returning a response"
                + (f": {stderr_text}" if stderr_text else "")
            )
        decoded = line.decode("utf-8", errors="replace").strip()
        if not decoded:
            return {}
        return json.loads(decoded)

    async def _read_stderr_tail(self) -> str:
        text = "".join(self._stderr_chunks).strip()
        return text[-800:]

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise ZhipuVisionMCPError("Vision MCP process is not running")
        return self._process

    async def _drain_stderr(self) -> None:
        process = self._require_process()
        if process.stderr is None:
            return
        try:
            while True:
                chunk = await process.stderr.readline()
                if not chunk:
                    break
                self._stderr_chunks.append(chunk.decode("utf-8", errors="replace"))
                if len(self._stderr_chunks) > 80:
                    self._stderr_chunks = self._stderr_chunks[-80:]
        except asyncio.CancelledError:
            raise


def _extract_tool_text(payload: dict[str, Any]) -> str:
    parts = payload.get("content")
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for item in parts:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip() != "text":
            continue
        text = str(item.get("text") or "").strip()
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


async def analyze_images_with_mcp(
    image_paths: list[Path] | list[str],
    *,
    prompt: str,
    timeout_sec: int = 90,
) -> list[VisionMCPAnalysisResult]:
    settings = get_settings()
    api_key = resolve_credential(
        mode=settings.zhipu_auth_mode,
        direct_value=settings.zhipu_api_key,
        helper_command=settings.zhipu_api_key_helper,
        provider_name="Zhipu",
    )
    catalog = build_zhipu_mcp_server_catalog(api_key=api_key, mcp_http_base_url=settings.zhipu_mcp_http_base_url)
    vision = catalog["vision"]
    env = os.environ.copy()
    env.update(dict(vision.env or {}))
    env.setdefault("Z_AI_API_KEY", api_key)
    env.setdefault("Z_AI_MODE", "ZHIPU")

    normalized_paths = [Path(str(path).strip()) for path in list(image_paths or []) if str(path).strip()]
    if not normalized_paths:
        return []

    results: list[VisionMCPAnalysisResult] = []
    command, args = _resolve_internal_command(vision.command or "npx", list(vision.args))
    async with _StdioMCPClient(
        command=command,
        args=args,
        env=env,
        timeout_sec=timeout_sec,
    ) as client:
        for image_path in normalized_paths:
            response = await client.call_tool(
                name="analyze_image",
                arguments={
                    "image_source": str(image_path),
                    "prompt": prompt,
                },
            )
            results.append(
                VisionMCPAnalysisResult(
                    image_path=str(image_path),
                    content=_extract_tool_text(response),
                    raw=response,
                )
            )
    return results


async def analyze_video_with_mcp(
    video_path: Path | str,
    *,
    prompt: str,
    timeout_sec: int = 180,
) -> VisionMCPAnalysisResult:
    settings = get_settings()
    api_key = resolve_credential(
        mode=settings.zhipu_auth_mode,
        direct_value=settings.zhipu_api_key,
        helper_command=settings.zhipu_api_key_helper,
        provider_name="Zhipu",
    )
    catalog = build_zhipu_mcp_server_catalog(api_key=api_key, mcp_http_base_url=settings.zhipu_mcp_http_base_url)
    vision = catalog["vision"]
    env = os.environ.copy()
    env.update(dict(vision.env or {}))
    env.setdefault("Z_AI_API_KEY", api_key)
    env.setdefault("Z_AI_MODE", "ZHIPU")

    normalized_path = Path(str(video_path).strip())
    if not str(normalized_path):
        raise ZhipuVisionMCPError("video path is empty")

    command, args = _resolve_internal_command(vision.command or "npx", list(vision.args))
    async with _StdioMCPClient(
        command=command,
        args=args,
        env=env,
        timeout_sec=timeout_sec,
    ) as client:
        response = await client.call_tool(
            name="analyze_video",
            arguments={
                "video_source": str(normalized_path),
                "prompt": prompt,
            },
        )
    return VisionMCPAnalysisResult(
        image_path=str(normalized_path),
        content=_extract_tool_text(response),
        raw=response,
    )


def _resolve_internal_command(command: str, args: list[str]) -> tuple[str, list[str]]:
    installed_binary = shutil.which("zai-mcp-server")
    if installed_binary:
        return installed_binary, []
    return command, list(args)
