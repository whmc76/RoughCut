from __future__ import annotations

from pathlib import Path
from typing import Any


async def infer_visual_semantic_evidence(frame_paths: list[Path] | list[str], capabilities: dict[str, Any]) -> dict[str, Any]:
    visual_capability = capabilities.get("visual_understanding") if isinstance(capabilities, dict) else {}
    mode = str((visual_capability or {}).get("mode") or "").strip()
    if mode == "native_multimodal":
        return await _infer_with_native_multimodal(frame_paths, capabilities)
    if mode in {"mcp", "visual_mcp"}:
        return await _infer_with_visual_mcp(frame_paths, capabilities)
    return {}


async def _infer_with_native_multimodal(frame_paths: list[Path] | list[str], capabilities: dict[str, Any]) -> dict[str, Any]:
    return _build_visual_semantic_stub(frame_paths=frame_paths, capabilities=capabilities, mode="native_multimodal")


async def _infer_with_visual_mcp(frame_paths: list[Path] | list[str], capabilities: dict[str, Any]) -> dict[str, Any]:
    return _build_visual_semantic_stub(frame_paths=frame_paths, capabilities=capabilities, mode="mcp")


def _build_visual_semantic_stub(
    *,
    frame_paths: list[Path] | list[str],
    capabilities: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    visual_capability = capabilities.get("visual_understanding") if isinstance(capabilities, dict) else {}
    provider = str((visual_capability or {}).get("provider") or "").strip()
    normalized_paths = [str(path).strip() for path in list(frame_paths or []) if str(path).strip()]
    return {
        "provider": provider,
        "mode": mode,
        "frame_paths": normalized_paths,
        "object_categories": [],
        "visible_brands": [],
        "visible_models": [],
        "subject_candidates": [],
        "interaction_type": "",
        "scene_context": "",
        "evidence_notes": [],
    }
