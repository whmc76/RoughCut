from __future__ import annotations

from pathlib import Path
from typing import Any


async def infer_visual_semantic_evidence(frame_paths: list[Path] | list[str], capabilities: dict[str, Any]) -> dict[str, Any]:
    visual_capability = capabilities.get("visual_understanding") if isinstance(capabilities, dict) else {}
    mode = str((visual_capability or {}).get("mode") or "").strip()
    if mode == "native_multimodal":
        return await _infer_with_native_multimodal(frame_paths, capabilities)
    if mode == "mcp":
        return await _infer_with_visual_mcp(frame_paths, capabilities)
    return {}


async def _infer_with_native_multimodal(frame_paths: list[Path] | list[str], capabilities: dict[str, Any]) -> dict[str, Any]:
    return {}


async def _infer_with_visual_mcp(frame_paths: list[Path] | list[str], capabilities: dict[str, Any]) -> dict[str, Any]:
    return {}
